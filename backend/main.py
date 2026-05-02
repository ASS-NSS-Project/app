import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from config import get_settings
from database import Base, engine, SessionLocal
# Side-effect import: registers ORM model classes with Base.metadata so that
# create_all() below discovers all tables. Without this line the import of Base
# happens before models.py is loaded and create_all() creates nothing.
import models  # noqa: F401
from models import Chunk
from routers import auth, sources, query, incidents
from routers import auth_keycloak
import routers.documents as documents_router
import routers.experiments as experiments_router
from services.auth import ensure_admin_exists, ensure_default_sources
from services.embedding import get_embedding_model
from services.logging_config import setup_logging
from services.rag import _get_embedder
from services.scheduler import create_scheduler

setup_logging(os.getenv("LOG_LEVEL", "INFO"))
# Without propagate=True, uvicorn's access log handler bypasses our JSON handler
# and writes plain-text lines directly to stderr, breaking Loki parsing.
logging.getLogger("uvicorn.access").propagate = True
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Code here runs on startup (before yield) and shutdown (after yield).
    
    On startup we:
    1. Create database tables
    2. Ensure admin user exists
    3. Initialize Qdrant collection
    """
    logger.info(
        "Starting up RAG System API container",
        extra={"event": "startup"}
    )

    # Create all tables — retries guard against Postgres DB not being fully ready yet.
    # First-time initdb state can take 30–60 s; thus 20 × 5 s = 100 s covers that.
    for attempt in range(1, 21):
        try:
            Base.metadata.create_all(bind=engine)

            logger.info("Database schema was created")

            break

        except Exception as e:
            if attempt == 20:
                raise

            logger.warning(
                "Database schema creation attempt %d/20 failed (%s), retrying in 5s…", 
                attempt, e
            )

            time.sleep(5)

    # Create admin user if none exists
    db = SessionLocal()
    
    try:
        ensure_admin_exists(db)
        ensure_default_sources(db)

    finally:
        db.close()

    # Load BGE-M3 weights eagerly — prevents OOMKill on first query.
    # Done before Qdrant init so a Qdrant failure doesn't skip model loading.
    try:
        get_embedding_model()
        logger.info("BGE-M3 model loaded", extra={"event": "model_load_complete"})
    except Exception as e:
        logger.warning("Could not pre-load embedding model: %s", e)

    # Initialize Qdrant collection
    # If the embedding model changed (different dimension), the collection is recreated
    # and all chunks are marked for re-embedding
    try:
        embedding_service = _get_embedder()
        db = SessionLocal()
        try:
            embedding_service.reconcile_with_db(db)
        finally:
            db.close()
        if embedding_service.collection_was_recreated:
            db = SessionLocal()
            try:
                count = db.query(Chunk).filter(Chunk.is_embedded == True).update(
                    {Chunk.is_embedded: False}
                )
                db.commit()
                logger.info(
                    f"Collection recreated after model change – "
                    f"{count} chunks marked for re-embedding"
                )
            finally:
                db.close()
        logger.info("Qdrant collection initialized")
    except Exception as e:
        logger.warning(f"Could not initialize Qdrant (will retry on first use): {e}")

    # Start the crawl scheduler – automatically schedules jobs every 5 minutes
    scheduler = create_scheduler()
    scheduler.start()
    logger.info("Crawl scheduler started")

    logger.info("Startup complete. API ready.")
    yield

    # Stop the scheduler when the application shuts down
    scheduler.shutdown(wait=False)
    logger.info("Shutting down...")


# Create the FastAPI application
# Disable interactive API docs in production to reduce attack surface.
# Set API_DOCS=true in .env to re-enable during development.
_docs_url = "/docs" if os.getenv("API_DOCS", "false").lower() == "true" else None
_redoc_url = "/redoc" if os.getenv("API_DOCS", "false").lower() == "true" else None
app = FastAPI(
    title="RAG System API",
    description="Multimodal web data collection and AI analysis system",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=_docs_url,
    redoc_url=_redoc_url,
)

# CORS: only the configured frontend origin may make credentialed requests.
_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[_settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register all API routers
# Each router handles a group of related endpoints
app.include_router(auth.router)
app.include_router(auth_keycloak.router)
app.include_router(sources.router)
app.include_router(query.router)
app.include_router(incidents.router)
app.include_router(documents_router.router)
app.include_router(experiments_router.router)


_SKIP_LOG_PATHS = {"/health", "/metrics"}


@app.middleware("http")
async def _log_requests(request: Request, call_next):
    if request.url.path in _SKIP_LOG_PATHS:
        return await call_next(request)
    t0 = time.monotonic()
    logger.info("→ %s %s", request.method, request.url.path, extra={
        "event": "http_request_start",
        "method": request.method,
        "path": request.url.path,
        "client": request.client.host if request.client else None,
    })
    try:
        response = await call_next(request)
        level = logging.WARNING if response.status_code >= 400 else logging.INFO
        logger.log(level, "%s %s %s", request.method, request.url.path, response.status_code, extra={
            "event": "http_request",
            "method": request.method,
            "path": request.url.path,
            "query": str(request.url.query) or None,
            "status": response.status_code,
            "duration_ms": round((time.monotonic() - t0) * 1000),
            "client": request.client.host if request.client else None,
        })
        return response
    except Exception as exc:
        logger.error("%s %s unhandled exception: %s", request.method, request.url.path, exc, extra={
            "event": "http_error",
            "method": request.method,
            "path": request.url.path,
            "duration_ms": round((time.monotonic() - t0) * 1000),
            "error": str(exc),
        }, exc_info=True)
        raise


@app.get("/health")
def health_check():
    return {"status": "ok", "service": "rag-api"}


@app.get("/metrics", include_in_schema=False)
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
