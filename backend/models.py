"""
models.py - Database Table Definitions

Each class here represents one table in PostgreSQL.
Class attributes represent columns in that table.

SQLAlchemy (the ORM we use) maps Python objects to SQL rows automatically:
- Creating a class instance creates a row.
- Setting an attribute updates a column.
- Calling db.query(Source).all() runs SELECT * FROM sources.

All primary keys are UUID strings (not auto-increment integers) so that IDs are
globally unique and safe to generate client-side without a DB round-trip.
"""

import uuid
import enum
from datetime import datetime
from sqlalchemy import (
    Column, String, Text, DateTime, Integer, Float,
    ForeignKey, Enum, Boolean, JSON, Index
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import relationship
from database import Base


def new_uuid() -> str:
    """Generate a new random UUID string. Used as the default for all primary key columns."""
    return str(uuid.uuid4())


# --- Enums
# Python enums stored as VARCHAR in Postgres. Using enums prevents typos
# and makes the allowed values self-documenting.

class UserRole(str, enum.Enum):
    """What a user is allowed to do in the system."""
    webrag_admin   = "webrag_admin"    # Full access: user management, Keycloak, Grafana
    webrag_curator = "webrag_curator"  # Manage sources, pipeline, and incidents
    webrag_analyst = "webrag_analyst"  # Run experiments and queries
    webrag_user    = "webrag_user"     # Query only — read-only access to the RAG system


class IngestStrategy(str, enum.Enum):
    """Which scraping method was used (or should be tried) for a source."""
    api         = "api"          # RSS/Atom feed via feedparser
    html        = "html"         # Raw HTTP + BeautifulSoup HTML parsing
    rendered    = "rendered"     # Playwright headless browser (for JS-heavy pages)
    screenshot  = "screenshot"   # Screenshot + VLM vision extraction
    upstream_ai = "upstream_ai"  # Delegated to an upstream AI service


class JobStatus(str, enum.Enum):
    """Lifecycle state of a single ingest attempt."""
    pending         = "pending"          # Queued, not yet picked up by a worker
    running         = "running"          # Worker is actively processing it
    done            = "done"             # Successfully scraped and saved
    failed          = "failed"           # Error during scraping or extraction
    captcha_blocked = "captcha_blocked"  # Target site returned a CAPTCHA


class EvidenceType(str, enum.Enum):
    """What kind of file was captured as evidence during scraping."""
    screenshot = "screenshot"  # PNG screenshot of the page
    html       = "html"        # Raw HTML source
    dom        = "dom"         # Rendered DOM (after JavaScript execution)
    pdf        = "pdf"         # PDF download


class IncidentType(str, enum.Enum):
    """Why an ingest job could not complete normally."""
    captcha      = "captcha"       # Site returned a CAPTCHA challenge
    rate_limited = "rate_limited"  # HTTP 429 / too many requests
    blocked      = "blocked"       # IP or user-agent was blocked by the site


class IncidentStatus(str, enum.Enum):
    """Resolution state of an incident (requires human review)."""
    open        = "open"         # Newly detected, no one has looked at it yet
    in_progress = "in_progress"  # Someone is investigating
    resolved    = "resolved"     # Fixed or accepted; no further action needed


class ChunkType(str, enum.Enum):
    """The structural type of a text chunk, used to choose chunking strategy."""
    text  = "text"   # Plain prose paragraph
    table = "table"  # HTML table converted to text
    block = "block"  # Visual block extracted by VLM from a screenshot


# --- User table
# Stores every account that can log into the system, whether via local password,
# Google OAuth, or Keycloak OIDC.

class User(Base):
    __tablename__ = "users"

    id       = Column(String, primary_key=True, default=new_uuid)
    username = Column(String, unique=True, nullable=True, index=True)
    email    = Column(String, unique=True, nullable=False, index=True)
    # Bcrypt hash of the password. NULL for OAuth-only users who never set a password.
    hashed_password = Column(String, nullable=True)
    full_name       = Column(String, nullable=True)
    role            = Column(Enum(UserRole), default=UserRole.webrag_user, nullable=False)
    is_active       = Column(Boolean, default=True)  # Soft disable without deleting the account
    created_at      = Column(DateTime, default=datetime.utcnow)

    # OAuth2 fields — only populated for users who authenticated via an external provider.
    # oauth_provider: which provider issued the token (e.g. "google", "keycloak")
    # oauth_id: the user's stable ID at that provider (used to match on re-login)
    oauth_provider = Column(String, nullable=True)
    oauth_id       = Column(String, nullable=True, index=True)
    avatar_url     = Column(String, nullable=True)  # Profile picture from Google/Keycloak

    # Opaque long-lived API token for programmatic access (curl, scripts, CI).
    # The raw token is shown only once at generation time; we store only the bcrypt hash.
    api_token_hash       = Column(String, nullable=True, index=True)
    api_token_created_at = Column(DateTime, nullable=True)
    api_token_expires_at = Column(DateTime, nullable=True)

    # Back-reference: user.audit_logs gives all audit entries for this user
    audit_logs = relationship("AuditLog", back_populates="user")


# --- Source table
# A "source" is a website or URL that the system should monitor and index.
# The scheduler checks which sources are due and queues ingest jobs for them.

class Source(Base):
    __tablename__ = "sources"

    id       = Column(String, primary_key=True, default=new_uuid)
    name     = Column(String, nullable=False)      # Human-readable label, e.g. "MENDELU News"
    base_url = Column(String, nullable=False)      # The URL to scrape

    # Legal/permission metadata — required to track data usage rights
    permission_type = Column(String, nullable=False)  # "public", "licensed", "api"
    permission_ref  = Column(Text, nullable=True)      # Reference to the agreement or URL

    # Scraping configuration
    preferred_strategy    = Column(Enum(IngestStrategy), default=IngestStrategy.api)
    crawl_frequency_hours = Column(Integer, default=24)   # How often to re-scrape
    crawl_depth           = Column(Integer, default=1)    # How many link levels to follow
    rate_limit_rps        = Column(Float, default=1.0)    # Requests per second (be polite)

    # Retention: how long to keep evidence and indexed content (in days)
    retention_days_evidence = Column(Integer, default=90)   # Screenshots, HTML dumps
    retention_days_index    = Column(Integer, default=365)  # Documents and chunks

    is_active  = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(String, ForeignKey("users.id"))

    # Set after each successful crawl. The scheduler compares
    # last_crawled_at + crawl_frequency_hours to now() to decide if a crawl is due.
    last_crawled_at = Column(DateTime, nullable=True)

    # Relationships — SQLAlchemy loads related rows lazily on first access
    jobs      = relationship("IngestJob", back_populates="source")
    documents = relationship("Document", back_populates="source")
    incidents = relationship("Incident", back_populates="source")


# --- IngestJob table
# Every time the system attempts to scrape a source, one IngestJob row is created.
# The worker picks up the job_id from RabbitMQ and updates this row as it progresses.

class IngestJob(Base):
    __tablename__ = "ingest_jobs"

    id            = Column(String, primary_key=True, default=new_uuid)
    source_id     = Column(String, ForeignKey("sources.id"), nullable=False)
    url           = Column(String, nullable=False)         # The exact URL that was scraped
    strategy_used = Column(Enum(IngestStrategy), nullable=True)  # Which strategy succeeded
    status        = Column(Enum(JobStatus), default=JobStatus.pending)

    # Timing — used to measure how long each scrape took
    started_at  = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    # Outcome
    error_message = Column(Text, nullable=True)    # Human-readable error if status=failed
    quality_score = Column(Float, nullable=True)   # 0.0–1.0 content quality estimate

    # Reserved for future external job tracking integrations
    rq_job_id = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    source   = relationship("Source", back_populates="jobs")
    evidence = relationship("Evidence", back_populates="job")


# --- Evidence table
# Every artifact captured during scraping (screenshot, HTML dump, etc.) is an evidence row.
# The actual file is stored in S3; this row holds the path, hash, and metadata.

class Evidence(Base):
    __tablename__ = "evidence"

    id     = Column(String, primary_key=True, default=new_uuid)
    job_id = Column(String, ForeignKey("ingest_jobs.id"), nullable=False)
    type   = Column(Enum(EvidenceType), nullable=False)

    # S3 object key, e.g. "evidence/2024/01/abc123.png"
    storage_uri = Column(String, nullable=False)
    # SHA-256 hash of the file — used to detect duplicate uploads
    file_hash       = Column(String, nullable=False)
    file_size_bytes = Column(Integer, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    job = relationship("IngestJob", back_populates="evidence")


# --- Document table
# The structured content extracted from a URL after scraping.
# One document per URL. When a source is re-scraped, doc_version increments
# and a new document row is created (the old one is kept for version history).

class Document(Base):
    __tablename__ = "documents"

    id        = Column(String, primary_key=True, default=new_uuid)
    source_id = Column(String, ForeignKey("sources.id"), nullable=False)
    url       = Column(String, nullable=False)
    title     = Column(String, nullable=True)

    # Version counter — increments each time this URL is re-scraped successfully
    doc_version = Column(Integer, default=1)

    # The full extracted content in Markdown format (stored inline for fast access)
    content_markdown = Column(Text, nullable=True)

    # S3 paths for resilient long-term storage
    markdown_uri = Column(String, nullable=True)  # Path to the .md file in S3
    chunks_uri   = Column(String, nullable=True)  # Path to chunks.json in S3

    # Legacy S3 path — kept for backwards compatibility, not actively written
    content_uri = Column(String, nullable=True)

    quality_score   = Column(Float, nullable=True)             # 0.0–1.0 extraction quality
    ingest_strategy = Column(Enum(IngestStrategy), nullable=True)
    # SHA-256 of content_markdown — used to skip re-embedding if content hasn't changed
    content_hash    = Column(String, nullable=True)

    language   = Column(String, nullable=True)  # ISO 639-1 code, e.g. "en", "cs"
    created_at = Column(DateTime, default=datetime.utcnow)

    source = relationship("Source", back_populates="documents")
    chunks = relationship("Chunk", back_populates="document")


# --- Chunk table
# A document is split into smaller "chunks" that fit within the embedding model's
# context window. Each chunk is independently embedded and stored in Qdrant.
# At query time, the most relevant chunks are retrieved and fed to the LLM.

class Chunk(Base):
    __tablename__ = "chunks"

    id          = Column(String, primary_key=True, default=new_uuid)
    document_id = Column(String, ForeignKey("documents.id"), nullable=False)
    chunk_type  = Column(Enum(ChunkType), default=ChunkType.text)

    text        = Column(Text, nullable=False)     # The actual text content of this chunk
    chunk_index = Column(Integer, nullable=False)  # Position within the document (0-based)

    # Citation info: when this chunk is shown to the user, we link back to the source URL
    citation_url         = Column(String, nullable=True)
    citation_evidence_id = Column(String, ForeignKey("evidence.id"), nullable=True)

    # For screenshot-extracted blocks: pixel coordinates within the screenshot image
    # Format: {"x": 10, "y": 20, "w": 300, "h": 50}
    bounding_box = Column(JSON, nullable=True)

    # Legacy boolean embedding flag — kept for backwards compatibility with old code paths
    is_embedded = Column(Boolean, default=False)

    # Fine-grained embedding status (replaces the legacy is_embedded flag)
    # Values: pending | in_progress | done | failed
    embedding_status = Column(String(20), nullable=False, default='pending', index=True)
    embedded_at      = Column(DateTime(timezone=True), nullable=True)   # When embedding completed
    embedding_error  = Column(Text, nullable=True)    # Last error message if status=failed
    retry_count      = Column(Integer, nullable=False, default=0)  # How many times we tried

    # Qdrant sync tracking — independently tracks whether the Qdrant vector is up to date
    # Values: synced | out_of_sync | missing
    qdrant_sync_status = Column(String(20), nullable=False, default='missing', index=True)
    qdrant_synced_at   = Column(DateTime(timezone=True), nullable=True)  # Last successful sync
    # Optional S3 backup path for the raw embedding vector (e.g. for disaster recovery)
    s3_embedding_uri = Column(String, nullable=True)

    # PostgreSQL tsvector column for full-text (keyword) search fallback.
    # Populated by a trigger or the ingest pipeline; used when Qdrant is unavailable.
    text_vector = Column(TSVECTOR, nullable=True)

    # Extended structural metadata
    parent_chunk_id = Column(String, ForeignKey("chunks.id"), nullable=True)  # For hierarchical chunks
    section_path    = Column(String, nullable=True)   # e.g. "Introduction > Background"
    token_count     = Column(Integer, nullable=True)  # Approximate token count of text
    source_method   = Column(String, nullable=True)   # "html" / "rendered" / "vlm"
    language        = Column(String, nullable=True)   # ISO 639-1 code

    created_at = Column(DateTime, default=datetime.utcnow)

    document = relationship("Document", back_populates="chunks")

    __table_args__ = (
        # GIN index on the tsvector column for fast full-text search (Postgres-native)
        Index('idx_chunk_text_vector', 'text_vector', postgresql_using='gin'),
    )


# --- Incident table
# When scraping fails due to a CAPTCHA, rate limit, or block, an incident is created
# so a human can investigate and decide how to proceed (e.g. rotate IP, use proxy).

class Incident(Base):
    __tablename__ = "incidents"

    id        = Column(String, primary_key=True, default=new_uuid)
    type      = Column(Enum(IncidentType), default=IncidentType.captcha)
    source_id = Column(String, ForeignKey("sources.id"), nullable=False)
    url       = Column(String, nullable=False)          # The URL that triggered the incident
    strategy  = Column(Enum(IngestStrategy), nullable=True)  # Strategy that was in use
    severity  = Column(String, default="medium")        # "low" | "medium" | "high"
    status    = Column(Enum(IncidentStatus), default=IncidentStatus.open)

    # Which part of the system detected this (e.g. "captcha_service", "http_client")
    detector = Column(String, nullable=True)

    # Screenshot of the CAPTCHA or block page, stored in S3
    evidence_screenshot_uri = Column(String, nullable=True)

    # Resolution tracking
    resolved_by     = Column(String, ForeignKey("users.id"), nullable=True)
    resolved_at     = Column(DateTime, nullable=True)
    resolution_note = Column(Text, nullable=True)  # Free-text explanation of how it was fixed

    created_at = Column(DateTime, default=datetime.utcnow)

    source = relationship("Source", back_populates="incidents")


# --- AuditLog table
# Immutable log of every significant action: who did what, when, to which object.
# Rows are only ever inserted, never updated or deleted.

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id          = Column(String, primary_key=True, default=new_uuid)
    # NULL if the action was performed by the system (e.g. scheduled job)
    user_id     = Column(String, ForeignKey("users.id"), nullable=True)
    action      = Column(String, nullable=False)      # e.g. "LOGIN", "SOURCE_CREATED", "QUERY"
    object_type = Column(String, nullable=True)       # e.g. "source", "document"
    object_id   = Column(String, nullable=True)       # UUID of the affected object
    # Arbitrary extra context: IP address, query text, HTTP status, etc.
    extra       = Column(JSON, nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="audit_logs")


# --- Experiment tables
# An Experiment is a batch of test queries used to measure RAG retrieval quality.
# After running, it stores aggregate metrics (recall, MRR, nDCG) for comparison.

class ExperimentStatus(str, enum.Enum):
    pending = "pending"  # Created but not yet started
    running = "running"  # Currently executing queries
    done    = "done"     # All queries completed, metrics computed
    failed  = "failed"   # One or more queries crashed


class Experiment(Base):
    __tablename__ = "experiments"

    id          = Column(String, primary_key=True, default=new_uuid)
    name        = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    created_by  = Column(String, ForeignKey("users.id"), nullable=False)
    status      = Column(Enum(ExperimentStatus), default=ExperimentStatus.pending)

    # Aggregate metrics — populated after the experiment finishes
    recall_at_k    = Column(Float, nullable=True)  # Fraction of expected keywords found in top-k
    mrr            = Column(Float, nullable=True)  # Mean Reciprocal Rank
    ndcg           = Column(Float, nullable=True)  # Normalised Discounted Cumulative Gain
    avg_latency_ms = Column(Float, nullable=True)  # Mean query latency across all queries

    top_k      = Column(Integer, default=5)         # How many chunks to retrieve per query
    model_name = Column(String, nullable=True)      # LLM model used during the experiment

    created_at    = Column(DateTime, default=datetime.utcnow)
    finished_at   = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)

    # cascade="all, delete-orphan" means deleting an experiment also deletes its queries
    queries = relationship("ExperimentQuery", back_populates="experiment", cascade="all, delete-orphan")


class ExperimentQuery(Base):
    """One test query within an experiment, with its expected keywords and per-query metrics."""
    __tablename__ = "experiment_queries"

    id            = Column(String, primary_key=True, default=new_uuid)
    experiment_id = Column(String, ForeignKey("experiments.id"), nullable=False)
    query_text    = Column(Text, nullable=False)
    # List of keywords that the retrieval result SHOULD contain for this query to pass
    expected_keywords = Column(JSON, nullable=False, default=list)  # list[str]

    # Per-query retrieval metrics (mirroring the experiment-level aggregates)
    recall_at_k         = Column(Float, nullable=True)
    mrr                 = Column(Float, nullable=True)
    ndcg                = Column(Float, nullable=True)
    latency_ms          = Column(Float, nullable=True)
    # The chunk IDs that were returned by Qdrant for this query
    retrieved_chunk_ids = Column(JSON, nullable=True)
    # The LLM-generated answer for this query
    generated_answer    = Column(Text, nullable=True)

    experiment = relationship("Experiment", back_populates="queries")
