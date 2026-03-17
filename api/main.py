"""
main.py - FastAPI Application Entry Point

This is what starts when you run: uvicorn main:app

It:
1. Creates all database tables on startup
2. Creates the first admin user
3. Registers all API routers (auth, sources, query, incidents)
4. Serves the frontend UI at /
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from database import engine, SessionLocal, Base
import models  # noqa: F401 - importing registers models with SQLAlchemy
from routers import auth, sources, query, incidents
from services.auth_service import ensure_admin_exists
from services.embedding_service import EmbeddingService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
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
    logger.info("Starting up RAG System...")

    # Create all tables defined in models.py
    # If tables already exist, this is a no-op (safe to run repeatedly)
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created/verified")

    # Create admin user if none exists
    db = SessionLocal()
    try:
        ensure_admin_exists(db)
    finally:
        db.close()

    # Initialize Qdrant collection
    try:
        EmbeddingService()  # Constructor creates collection if needed
        logger.info("Qdrant collection initialized")
    except Exception as e:
        logger.warning(f"Could not initialize Qdrant (will retry on first use): {e}")

    logger.info("Startup complete. API ready.")
    yield
    logger.info("Shutting down...")


# Create the FastAPI application
app = FastAPI(
    title="RAG System API",
    description="Multimodal web data collection and AI analysis system",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS: Allow the frontend (running on the same origin) to make requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # In production, restrict this to your domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register all API routers
# Each router handles a group of related endpoints
app.include_router(auth.router)
app.include_router(sources.router)
app.include_router(query.router)
app.include_router(incidents.router)

# Serve static files (the frontend)
# Files in /app/static/ are served at /static/
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def serve_frontend():
    """Serve the frontend HTML app."""
    return FileResponse("static/index.html")


@app.get("/health")
def health_check():
    """Simple health check endpoint for monitoring."""
    return {"status": "ok", "service": "rag-api"}
