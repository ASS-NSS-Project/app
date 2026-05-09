"""
config.py - Application Settings

All configuration is read from environment variables (or a .env file for local dev).
Pydantic-settings reads them automatically, validates their types, and raises a clear
error if a required variable is missing or has the wrong type.

Why environment variables?
- Secrets (passwords, API keys) are never hardcoded in source code.
- The same Docker image runs in dev, staging, and production — only the env differs.
- Kubernetes injects values from Secrets and ConfigMaps at runtime.

Usage anywhere in the codebase:
    from config import get_settings
    settings = get_settings()
    print(settings.database_url)
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


# --- Chunking config (nested settings classes)
# These control how long each text chunk can be (measured in tokens, not characters).
# Tokens are roughly 3/4 of a word. 500 tokens ≈ 375 words.

class ProseChunkConfig(BaseSettings):
    """Settings for splitting plain prose paragraphs into chunks."""
    model_config = SettingsConfigDict(env_nested_delimiter='__')
    # Ideal chunk size — large enough for context, small enough for precision
    target_tokens: int = 500
    # How many tokens to repeat from the previous chunk (for context continuity)
    overlap_tokens: int = 50
    # Chunks smaller than this are merged with the next one
    min_tokens: int = 100
    # Hard cap — chunks larger than this are always split
    max_tokens: int = 800


class TableChunkConfig(BaseSettings):
    """Settings for splitting HTML tables into chunks."""
    model_config = SettingsConfigDict(env_nested_delimiter='__')
    # Tables can be larger than prose since their rows are structured
    max_tokens: int = 1500
    # If a table is split, repeat the header row in each chunk so it stays readable
    repeat_header_on_split: bool = True


class VlmChunkConfig(BaseSettings):
    """Settings for splitting VLM (vision model) extracted text blocks."""
    model_config = SettingsConfigDict(env_nested_delimiter='__')
    max_tokens: int = 800
    # Honour the block boundaries detected by the VLM instead of cutting mid-block
    respect_block_boundaries: bool = True


class ChunkConfig(BaseSettings):
    """Container for all three chunk-type configs."""
    model_config = SettingsConfigDict(env_nested_delimiter='__')
    prose: ProseChunkConfig = ProseChunkConfig()
    table: TableChunkConfig = TableChunkConfig()
    vlm: VlmChunkConfig = VlmChunkConfig()


class Settings(BaseSettings):
    """
    Main application settings.

    Every attribute maps 1:1 to an environment variable of the same name in
    UPPER_CASE (pydantic-settings handles the conversion automatically).
    Example: `postgres_user` reads from `POSTGRES_USER`.

    Nested objects use double-underscore as separator:
    `chunking__prose__target_tokens` maps to `chunking.prose.target_tokens`.
    """
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_nested_delimiter='__')

    # --- Database
    postgres_user: str = "raguser"
    postgres_password: str = "changeme"
    postgres_db: str = "ragdb"
    # Hostname of the Postgres container (service name in Docker Compose / K8s)
    postgres_host: str = "postgres"

    @property
    def database_url(self) -> str:
        """Builds the SQLAlchemy connection string from the four postgres_* fields."""
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}/{self.postgres_db}"
        )

    # --- RabbitMQ
    # Full AMQP URL including credentials, host, and vhost
    rabbitmq_url: str = "amqp://guest:guest@rabbitmq:5672/"

    # --- S3 object storage (CESNET e-INFRA in production, MinIO in local dev)
    s3_endpoint_url: str = ""         # e.g. https://s3.cl2.du.cesnet.cz
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = "us-east-1"
    # Path-style URLs are required for MinIO; CESNET uses virtual-hosted style (false)
    s3_use_path_style: bool = True
    s3_bucket_evidence: str = "rag-evidence"   # Screenshots and HTML dumps
    s3_bucket_docs: str = "rag-documents"      # Processed markdown and chunk JSON

    # --- Qdrant (vector database)
    qdrant_url: str = "http://qdrant.qdrant.svc:6333"
    # Name of the collection that stores all chunk vectors
    qdrant_collection: str = "rag_chunks"
    # How many Qdrant nodes store a copy of each vector shard.
    # 1 = no replication (single node is fine for local dev).
    # 3 = every shard lives on 3 nodes; cluster survives losing any single node.
    qdrant_replication_factor: int = 1

    # --- LLM (text generation — any OpenAI-compatible endpoint)
    query_base_url: str = ""    # e.g. https://llm.ai.e-infra.cz/v1
    query_api_key: str = ""
    query_model: str = ""       # e.g. qwen3.5-122b

    # --- VLM (vision extraction — may use a different endpoint/model from the LLM)
    vlm_base_url: str = ""
    vlm_api_key: str = ""
    vlm_model: str = ""         # Must be a multimodal model that accepts image input

    # --- Embeddings (local BGE-M3 model loaded via FlagEmbedding)
    embedding_model: str = "BAAI/bge-m3"   # HuggingFace model ID
    embedding_dim: int = 1024              # Dense vector dimension for this model
    embedding_timeout_minutes: int = 5    # Per-document embedding timeout
    enable_embedding_backup_s3: bool = False  # Optionally backup raw vectors to S3
    s3_bucket_embeddings: str = "rag-embeddings"

    # --- Authentication
    jwt_secret: str = "changeme"       # MUST be overridden in production
    jwt_algorithm: str = "HS256"       # HMAC-SHA256 signing algorithm
    jwt_expire_minutes: int = 480      # 8 hours — browser session lifetime
    # Long-lived API tokens for programmatic access (curl, scripts, etc.)
    api_token_expire_hours: int = 2160  # 90 days

    # --- Keycloak OIDC (optional for local dev, required in production)
    keycloak_url: str = ""                     # e.g. https://keycloak.nss.jkzl.eu
    keycloak_internal_url: str = ""            # e.g. http://keycloak:8080 in Docker Compose
    keycloak_realm: str = "ass-nss-project"
    keycloak_client_id: str = ""
    keycloak_client_secret: str = ""
    keycloak_redirect_uri: str = "http://localhost/auth/keycloak/callback"
    # Allowed CORS origin — must match the URL users access the frontend from
    frontend_url: str = "http://localhost"

    # --- First Admin (created automatically on first startup if no admin exists)
    first_admin_username: str = "admin"
    first_admin_email: str = "admin@example.com"
    first_admin_password: str = "changeme"   # Override in production via Vault/ESO

    # --- Default sources (seeded into the DB on startup if the sources table is empty)
    # Comma-separated entries of the form "url|strategy" (strategy optional, defaults to html).
    # Valid strategies: html, rendered, screenshot, api
    # Example: https://mendelu.cz|html,https://example.com|rendered
    default_source_urls: str = ""

    # --- Ingest settings
    # Minimum number of characters that scraped content must have to be considered valid.
    # Content shorter than this is treated as a failed extraction (e.g. empty page).
    quality_threshold_chars: int = 200

    # --- Chunking configuration (see nested classes above)
    chunking: ChunkConfig = ChunkConfig()

    # --- Fallback search (used when Qdrant is unavailable)
    # If Qdrant is down or unreachable, fall back to full-text search in Postgres
    enable_keyword_fallback: bool = True
    fallback_search_engine: str = "postgres_tsvector"  # or: bm25, simple
    # How long to wait for Qdrant health check before declaring it unavailable (seconds)
    qdrant_health_check_timeout: float = 2.0

    # --- Healing and sync (background jobs that keep Qdrant in sync with Postgres)
    # How often the heal/drift-check jobs run (minutes)
    heal_interval_minutes: int = 15
    # If more than this % of chunks are missing from Qdrant, trigger an alert
    drift_alert_threshold_pct: float = 10.0
    # Automatically re-embed chunks that are out of sync (vs. just alerting)
    auto_resync_on_drift: bool = True

    # --- API docs (Swagger UI and ReDoc — disabled by default to reduce attack surface)
    api_docs: bool = False


@lru_cache()
def get_settings() -> Settings:
    """
    Returns the singleton Settings instance.

    @lru_cache ensures the .env file is read only once, no matter how many
    modules call get_settings(). Subsequent calls return the cached object.
    """
    return Settings()
