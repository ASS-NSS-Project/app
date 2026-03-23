"""
config.py - Application Settings

All configuration comes from environment variables (set in .env file).
Pydantic reads them automatically and validates types.

Why environment variables? So you never hardcode secrets in code,
and you can change settings without modifying files.
"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # ── Database ──────────────────────────────────
    postgres_user: str = "raguser"
    postgres_password: str = "changeme"
    postgres_db: str = "ragdb"
    postgres_host: str = "postgres"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}/{self.postgres_db}"
        )

    # ── RabbitMQ ──────────────────────────────────
    rabbitmq_url: str = "amqp://guest:guest@rabbitmq:5672/"

    # ── MinIO ─────────────────────────────────────
    minio_endpoint: str = "minio:9000"
    minio_root_user: str = "minioadmin"
    minio_root_password: str = "minioadmin"
    minio_bucket_evidence: str = "evidence"   # Where screenshots/HTML are stored
    minio_bucket_docs: str = "documents"      # Where structured documents are stored

    # ── Qdrant ────────────────────────────────────
    qdrant_host: str = "qdrant"
    qdrant_port: int = 6333
    qdrant_collection: str = "rag_chunks"     # Name of the vector collection

    # ── Ollama (local LLM inference) ──────────────
    ollama_base_url: str = "http://ollama:11434/v1"
    ollama_model: str = "llama3.2:3b"          # Text model for RAG answers
    ollama_vision_model: str = "qwen3-vl:2b"   # Vision model for screenshot extraction

    # ── Embeddings (local sentence-transformers) ──
    embedding_model: str = "BAAI/bge-m3"   # Multilingual model, higher quality (~570MB)
    embedding_dim: int = 1024              # BGE-M3 output: 1024-dimensional vectors

    # ── Authentication ────────────────────────────
    jwt_secret: str = "changeme"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480  # 8 hours

    # ── Google OAuth2 ─────────────────────────────
    # Obtain these values from Google Cloud Console (see README for instructions)
    google_client_id: str = ""
    google_client_secret: str = ""
    # Must match what you configure in Google Cloud Console
    google_redirect_uri: str = "http://localhost:8000/auth/google/callback"
    # Frontend URL – we redirect here after successful login with the JWT token
    frontend_url: str = "http://localhost:8000"

    # ── First Admin (created on startup) ──────────
    first_admin_username: str = "admin"
    first_admin_email: str = "admin@example.com"
    first_admin_password: str = "changeme"

    # ── Ingest settings ───────────────────────────
    # How many characters does extracted content need to be "good enough"?
    quality_threshold_chars: int = 200
    # Max chunk size for splitting documents
    chunk_size: int = 800
    chunk_overlap: int = 100

    class Config:
        env_file = ".env"
        extra = "ignore"


# lru_cache means this function only runs once and is cached.
# Everyone who calls get_settings() gets the same object.
@lru_cache()
def get_settings() -> Settings:
    return Settings()
