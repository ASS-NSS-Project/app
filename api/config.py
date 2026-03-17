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

    # ── Redis ─────────────────────────────────────
    redis_url: str = "redis://redis:6379"

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

    # ── Anthropic ─────────────────────────────────
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-4-5"         # Used for vision + RAG answers
    anthropic_vision_model: str = "claude-opus-4-5"  # Same model, vision capable

    # ── Embeddings (local sentence-transformers) ──
    embedding_model: str = "all-MiniLM-L6-v2"   # Small, fast, good quality (~90MB)
    embedding_dim: int = 384                      # This model outputs 384-dim vectors

    # ── Authentication ────────────────────────────
    jwt_secret: str = "changeme"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480  # 8 hours

    # ── First Admin (created on startup) ──────────
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
