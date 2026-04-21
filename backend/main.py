import logging
import os
import time
from contextlib import asynccontextmanager

from alembic.config import Config as AlembicConfig
from alembic import command as alembic_command
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from config import get_settings
from database import SessionLocal
import models  # noqa: F401
from models import Chunk, Experiment, ExperimentStatus
from routers import auth, sources, query, incidents
from routers import auth_google
import routers.documents as documents_router
import routers.experiments as experiments_router
from services.auth_service import ensure_admin_exists
from services.embedding_service import EmbeddingService
from services.logging_config import setup_logging
from services.scheduler_service import create_scheduler

setup_logging(os.getenv("LOG_LEVEL", "INFO"))
logging.getLogger("uvicorn.access").propagate = True
logger = logging.getLogger(__name__)


def _run_migrations() -> None:
    """
    Programmatically run Alembic migrations (equivalent to `alembic upgrade head`).
    Called on startup instead of Base.metadata.create_all().

    Advantages over create_all:
    - Tracks migration history (alembic_version table)
    - Supports rollback (downgrade)
    - Can auto-generate migrations when models change
    """
    # Path to alembic.ini is relative to this file (main.py lives in /app)
    alembic_cfg = AlembicConfig(os.path.join(os.path.dirname(__file__), "alembic.ini"))
    # Explicitly set script path so it works inside Docker too
    alembic_cfg.set_main_option(
        "script_location",
        os.path.join(os.path.dirname(__file__), "alembic"),
    )
    alembic_command.upgrade(alembic_cfg, "head")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Code here runs on startup (before yield) and shutdown (after yield).
    
    On startup we:
    1. Create database tables
    2. Ensure admin user exists
    3. Initialize Qdrant collection
    """
    logger.info("Starting up RAG System API", extra={"event": "startup"})

    # Run Alembic migrations with retries — guards against postgres not being
    # fully ready yet (podman-compose does not fully honour condition: service_healthy).
    # First-time initdb can take 30–60 s; 20 × 5 s = 100 s covers that.
    for attempt in range(1, 21):
        try:
            _run_migrations()
            logger.info("Database migrations complete")
            break
        except Exception as e:
            if attempt == 20:
                raise
            logger.warning("Migration attempt %d/20 failed (%s), retrying in 5s…", attempt, e)
            time.sleep(5)

    # Create admin user if none exists
    db = SessionLocal()
    try:
        ensure_admin_exists(db)

        # Reset experiments stuck in "running" — they were interrupted by a previous restart
        stuck = db.query(Experiment).filter(Experiment.status == ExperimentStatus.running).all()
        for exp in stuck:
            exp.status = ExperimentStatus.failed
            exp.error_message = "Interrupted by API restart"
        if stuck:
            db.commit()
            logger.info("Reset %d stuck experiment(s) to failed", len(stuck))
    finally:
        db.close()

    # Initialize Qdrant collection
    # If the embedding model changed (different dimension), the collection is recreated
    # and all chunks are marked for re-embedding
    try:
        embedding_service = EmbeddingService()
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
app.include_router(auth_google.router)
app.include_router(sources.router)
app.include_router(query.router)
app.include_router(incidents.router)
app.include_router(documents_router.router)
app.include_router(experiments_router.router)


@app.get("/health")
def health_check():
    return {"status": "ok", "service": "rag-api"}


@app.get("/metrics", include_in_schema=False)
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
