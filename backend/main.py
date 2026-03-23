"""
main.py - FastAPI application entry point

Run with: uvicorn main:app

On startup:
1. Runs Alembic migrations (upgrade head) – applies all pending schema changes
2. Creates the first administrator if none exists
3. Registers all API routers (auth, sources, query, incidents)
4. Serves the frontend UI at /
"""

import logging
import os
from contextlib import asynccontextmanager

from alembic.config import Config as AlembicConfig
from alembic import command as alembic_command
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings
from database import SessionLocal
import models  # noqa: F401 - required to register models with SQLAlchemy
from models import Chunk
from routers import auth, sources, query, incidents
from routers import auth_google
from services.auth_service import ensure_admin_exists
from services.embedding_service import EmbeddingService
from services.scheduler_service import create_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
# uvicorn.access has its own handlers and sets propagate=False by default,
# which means its access log lines never reach our root handler / docker logs.
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
    logger.info("Starting up RAG System...")

    # Run Alembic migrations – applies all pending migrations (upgrade head)
    # Safe to re-run: Alembic skips migrations that have already been applied
    _run_migrations()
    logger.info("Database migrations complete")

    # Create admin user if none exists
    db = SessionLocal()
    try:
        ensure_admin_exists(db)
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
app.include_router(auth_google.router)   # Google OAuth2 login
app.include_router(sources.router)
app.include_router(query.router)
app.include_router(incidents.router)

@app.get("/health")
def health_check():
    """Simple health check endpoint for monitoring."""
    return {"status": "ok", "service": "rag-api"}
