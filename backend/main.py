"""
main.py - FastAPI Application Entry Point

This file does three things:
1. Runs startup logic (DB schema, admin user, Qdrant init, scheduler) via the lifespan hook.
2. Configures the FastAPI app (CORS, middleware, routers).
3. Exposes /health and /metrics endpoints.

Uvicorn starts this file:
    uvicorn main:app --host 0.0.0.0 --port 8000
"""

import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from sqlalchemy import text

from config import get_settings
from database import Base, engine, SessionLocal
# Side-effect import: registers ORM model classes with Base.metadata so that
# create_all() below discovers all tables. Without this import, Base is loaded
# before models.py and create_all() finds no tables to create.
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

# setup_logging must be called first, before any other import logs anything.
# It replaces the default uvicorn plain-text handler with our JSON handler.
setup_logging(os.getenv("LOG_LEVEL", "INFO"))
# Without propagate=True, uvicorn's access log handler bypasses our JSON handler
# and writes plain-text lines directly to stderr, breaking Loki parsing.
logging.getLogger("uvicorn.access").propagate = True
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup and shutdown logic for the FastAPI application.

    Everything before `yield` runs on startup; everything after runs on shutdown.
    FastAPI calls this automatically when the server starts and stops.

    Startup sequence:
    1. Create/migrate DB schema (with retry loop for slow Postgres first-boot)
    2. Backfill any schema columns added after initial deploy
    3. Create the first admin user if none exists
    4. Seed default sources if configured
    5. Pre-load the BGE-M3 embedding model into RAM (prevents OOMKill on first query)
    6. Initialise the Qdrant collection (creates it if missing, recreates if model changed)
    7. Start the APScheduler crawl scheduler
    """
    logger.info("Starting up RAG System API container", extra={"event": "startup"})

    # Create all DB tables defined in models.py.
    # Retries guard against Postgres not being fully ready yet on first boot —
    # CNPG / Docker Compose can take 30–60 s to initialise the DB cluster.
    # 20 retries × 5 s = up to 100 s of patience before giving up.
    for attempt in range(1, 21):
        try:
            Base.metadata.create_all(bind=engine)
            logger.info("Database schema was created")

            # Backfill API token columns that were added after the initial schema.
            # IF NOT EXISTS makes this idempotent — safe to run on every startup.
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS api_token_hash VARCHAR"))
                conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS api_token_created_at TIMESTAMP"))
                conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS api_token_expires_at TIMESTAMP"))
                conn.commit()

            break

        except Exception as e:
            if attempt == 20:
                raise  # Give up and crash — Kubernetes will restart the pod

            logger.warning(
                "Database schema creation attempt %d/20 failed (%s), retrying in 5s…",
                attempt, e,
            )
            time.sleep(5)

    # Ensure the bootstrap admin user exists (idempotent — skips if already present)
    db = SessionLocal()
    try:
        ensure_admin_exists(db)
        # Seed any default sources configured via the DEFAULT_SOURCE_URLS env var
        ensure_default_sources(db)
    finally:
        db.close()

    # Pre-load BGE-M3 model weights into memory eagerly.
    # If we skip this, the first /query request would trigger a ~30 s model load
    # under load, likely causing an OOMKill or request timeout.
    # We do this before Qdrant init so a Qdrant failure doesn't prevent model loading.
    try:
        get_embedding_model()
        logger.info("BGE-M3 model loaded", extra={"event": "model_load_complete"})
    except Exception as e:
        logger.warning("Could not pre-load embedding model: %s", e)

    # Initialise the Qdrant vector collection.
    # reconcile_with_db() checks whether Qdrant has orphaned vectors with no matching
    # Postgres chunks (can happen after a DB reset) and clears them.
    # _ensure_collection() (called inside EmbeddingService.__init__) creates the
    # collection if it doesn't exist, or recreates it if the vector format changed.
    try:
        embedding_service = _get_embedder()
        db = SessionLocal()
        try:
            embedding_service.reconcile_with_db(db)
        finally:
            db.close()

        if embedding_service.collection_was_recreated:
            # The collection was recreated (e.g. embedding model changed dimension).
            # Mark all previously-embedded chunks as pending so the embed worker
            # picks them up and re-embeds them into the new collection format.
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

    # Start the background scheduler that periodically queues ingest jobs for due sources
    scheduler = create_scheduler()
    scheduler.start()
    logger.info("Crawl scheduler started")

    logger.info("Startup complete. API ready.")
    yield  # The application runs here — everything below runs on shutdown

    # Graceful shutdown: stop the scheduler without waiting for running jobs to finish
    scheduler.shutdown(wait=False)
    logger.info("Shutting down...")


# Conditionally enable interactive API docs.
# Disabled by default in production to reduce attack surface (no public Swagger UI).
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

# CORS (Cross-Origin Resource Sharing): browsers block requests from one origin to
# another unless the server explicitly allows it. We whitelist only our frontend URL.
_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[_settings.frontend_url],
    allow_credentials=True,   # Allows the browser to send cookies and Authorization headers
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register all API routers — each handles a group of related endpoints
app.include_router(auth.router)           # /auth/login, /auth/register, /auth/me, etc.
app.include_router(auth_keycloak.router)  # /auth/keycloak, /auth/keycloak/callback
app.include_router(sources.router)        # /sources CRUD + /sources/{id}/ingest
app.include_router(query.router)          # /query
app.include_router(incidents.router)      # /incidents
app.include_router(documents_router.router)    # /documents, /documents/{id}/chunks
app.include_router(experiments_router.router)  # /experiments

# Paths that are polled frequently by Kubernetes and Prometheus — skip request logging
# to avoid filling Loki with thousands of health-check lines per hour.
_SKIP_LOG_PATHS = {"/health", "/metrics"}


@app.middleware("http")
async def _log_requests(request: Request, call_next):
    """
    HTTP middleware that logs every request and response as structured JSON.

    Logs two events per request:
    - http_request_start: method + path + client IP (before processing)
    - http_request: method + path + status code + duration (after response)

    Skips /health and /metrics to avoid log noise.
    Logs 4xx/5xx responses at WARNING level so they stand out in Loki.
    """
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
        # Warn on 4xx/5xx so errors are visible in Loki without a filter
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
    """
    Kubernetes liveness and readiness probe endpoint.
    Returns 200 OK as long as the process is alive and the event loop is running.
    Does NOT check database or Qdrant connectivity — that would be too slow.
    """
    return {"status": "ok", "service": "rag-api"}


@app.get("/metrics", include_in_schema=False)
def metrics():
    """
    Prometheus metrics endpoint.
    Returns all registered counters, histograms, and gauges in the Prometheus text format.
    Scraped by the PodMonitor every 30 seconds and stored in Prometheus.
    """
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
