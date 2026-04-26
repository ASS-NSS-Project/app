"""
config.py - Application Settings

All configuration comes from environment variables (set in .env file).
Pydantic reads them automatically and validates types.

Why environment variables? So you never hardcode secrets in code,
and you can change settings without modifying files.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


# ── Chunking config (nested) ──────────────────────

class ProseChunkConfig(BaseSettings):
    model_config = SettingsConfigDict(env_nested_delimiter='__')
    target_tokens: int = 500
    overlap_tokens: int = 50
    min_tokens: int = 100
    max_tokens: int = 800


class TableChunkConfig(BaseSettings):
    model_config = SettingsConfigDict(env_nested_delimiter='__')
    max_tokens: int = 1500
    repeat_header_on_split: bool = True


class VlmChunkConfig(BaseSettings):
    model_config = SettingsConfigDict(env_nested_delimiter='__')
    max_tokens: int = 800
    respect_block_boundaries: bool = True


class ChunkConfig(BaseSettings):
    model_config = SettingsConfigDict(env_nested_delimiter='__')
    prose: ProseChunkConfig = ProseChunkConfig()
    table: TableChunkConfig = TableChunkConfig()
    vlm: VlmChunkConfig = VlmChunkConfig()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_nested_delimiter='__')

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

    # ── S3 object storage (CESNET e-INFRA) ────────
    s3_endpoint_url: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = "us-east-1"
    s3_use_path_style: bool = True
    s3_bucket_evidence: str = "rag-evidence"
    s3_bucket_docs: str = "rag-documents"

    # ── Qdrant ────────────────────────────────────
    qdrant_url: str = "http://qdrant.qdrant.svc:6333"
    qdrant_collection: str = "rag_chunks"

    # ── AIaaS (e-INFRA, shared base URL + key for LLM and VLM) ──
    aiaas_base_url: str = ""
    aiaas_api_key: str = ""

    # ── LLM (text generation) ─────────────────────
    aiaas_llm_model: str = ""

    # ── VLM (vision extraction) ───────────────────
    aiaas_vlm_model: str = ""

    # ── Optional external LLM providers ──────────
    # Set these to enable the corresponding models in the query UI.
    openai_api_key: str = ""     # enables GPT-4.1, GPT-4o, o4-mini, o3 family
    gemini_api_key: str = ""     # enables Gemini 2.5, 3.0, 3.1 family
    anthropic_api_key: str = ""  # enables Claude Opus 4.7, Sonnet 4.6, Haiku 4.5

    # ── Embeddings (local FlagEmbedding / BGE-M3) ─
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024

    # ── Authentication ────────────────────────────
    jwt_secret: str = "changeme"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480  # 8 hours

    # ── Keycloak OIDC ──────────────────────────────
    keycloak_url: str = ""              # e.g. https://keycloak.nss.jkzl.eu
    keycloak_realm: str = "ass-nss-project"
    keycloak_client_id: str = ""
    keycloak_client_secret: str = ""
    keycloak_redirect_uri: str = "http://localhost/auth/keycloak/callback"
    keycloak_admin_client_id: str = ""      # service account: rag-rbac-sa
    keycloak_admin_client_secret: str = ""  # service account secret
    frontend_url: str = "http://localhost"

    # ── First Admin (created on startup) ──────────
    first_admin_username: str = "admin"
    first_admin_email: str = "admin@example.com"
    first_admin_password: str = "changeme"

    # ── Default sources (seeded on startup) ──────
    # Comma-separated entries of the form "url|strategy" (strategy optional, defaults to html).
    # Valid strategies: html, rendered, screenshot, api
    # Example: https://mendelu.cz|html,https://example.com|rendered
    default_source_urls: str = ""

    # ── Ingest settings ───────────────────────────
    quality_threshold_chars: int = 200

    # ── Chunking configuration ────────────────────
    chunking: ChunkConfig = ChunkConfig()


@lru_cache()
def get_settings() -> Settings:
    return Settings()
