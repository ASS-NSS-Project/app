"""
models.py - Database Table Definitions

Each class here = one table in PostgreSQL.
The class attributes = columns in that table.

This matches the data model described in Section 14 of the requirements document.
"""

import uuid
import enum
from datetime import datetime
from sqlalchemy import (
    Column, String, Text, DateTime, Integer, Float,
    ForeignKey, Enum, Boolean, JSON
)
from sqlalchemy.orm import relationship
from database import Base


def new_uuid() -> str:
    """Generate a new UUID string. Used as primary keys."""
    return str(uuid.uuid4())


# ─────────────────────────────────────────────────────
# ENUMS - predefined sets of allowed values
# ─────────────────────────────────────────────────────

class UserRole(str, enum.Enum):
    admin = "admin"       # Full system access
    curator = "curator"   # Manage sources and incidents
    analyst = "analyst"   # Run experiments and reports
    user = "user"         # Query only


class IngestStrategy(str, enum.Enum):
    api = "api"
    html = "html"
    rendered = "rendered"
    screenshot = "screenshot"
    upstream_ai = "upstream_ai"


class JobStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"
    captcha_blocked = "captcha_blocked"


class EvidenceType(str, enum.Enum):
    screenshot = "screenshot"
    html = "html"
    dom = "dom"
    pdf = "pdf"


class IncidentType(str, enum.Enum):
    captcha = "captcha"
    rate_limited = "rate_limited"
    blocked = "blocked"


class IncidentStatus(str, enum.Enum):
    open = "open"
    in_progress = "in_progress"
    resolved = "resolved"


class ChunkType(str, enum.Enum):
    text = "text"
    table = "table"
    block = "block"


# ─────────────────────────────────────────────────────
# USER TABLE
# Who can log in and what they can do.
# ─────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=new_uuid)
    username = Column(String, unique=True, nullable=True, index=True)
    email = Column(String, unique=True, nullable=False, index=True)
    # Password is optional – users who log in via Google don't have one
    hashed_password = Column(String, nullable=True)
    full_name = Column(String, nullable=True)
    role = Column(Enum(UserRole), default=UserRole.user, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # OAuth2 fields – only populated for users who log in via an external provider
    oauth_provider = Column(String, nullable=True)   # e.g. "google"
    oauth_id = Column(String, nullable=True, index=True)  # Google sub (unique user ID)
    avatar_url = Column(String, nullable=True)        # Profile picture URL from Google

    audit_logs = relationship("AuditLog", back_populates="user")


# ─────────────────────────────────────────────────────
# SOURCE TABLE
# A "source" is a website or URL pattern we want to monitor.
# Example: { name: "Tech Blog", base_url: "https://techblog.com" }
# ─────────────────────────────────────────────────────

class Source(Base):
    __tablename__ = "sources"

    id = Column(String, primary_key=True, default=new_uuid)
    name = Column(String, nullable=False)
    base_url = Column(String, nullable=False)
    
    # Legal/permission info (required by section 2 of spec)
    permission_type = Column(String, nullable=False)  # e.g. "public", "licensed", "api"
    permission_ref = Column(Text, nullable=True)       # Reference to the agreement

    # How to collect
    preferred_strategy = Column(Enum(IngestStrategy), default=IngestStrategy.api)
    crawl_frequency_hours = Column(Integer, default=24)
    crawl_depth = Column(Integer, default=1)
    rate_limit_rps = Column(Float, default=1.0)  # Requests per second

    # How long to keep evidence (days)
    retention_days_evidence = Column(Integer, default=90)
    retention_days_index = Column(Integer, default=365)

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(String, ForeignKey("users.id"))

    # Timestamp of the last successful crawl – used by the scheduler to determine
    # whether the source is "due" (last_crawled_at + crawl_frequency_hours <= now)
    last_crawled_at = Column(DateTime, nullable=True)

    # Relationships (lets you do source.jobs to get all jobs for this source)
    jobs = relationship("IngestJob", back_populates="source")
    documents = relationship("Document", back_populates="source")
    incidents = relationship("Incident", back_populates="source")


# ─────────────────────────────────────────────────────
# INGEST JOB TABLE
# Every time we attempt to scrape a URL, one job is created.
# Tracks status, which strategy was used, errors, etc.
# ─────────────────────────────────────────────────────

class IngestJob(Base):
    __tablename__ = "ingest_jobs"

    id = Column(String, primary_key=True, default=new_uuid)
    source_id = Column(String, ForeignKey("sources.id"), nullable=False)
    url = Column(String, nullable=False)
    strategy_used = Column(Enum(IngestStrategy), nullable=True)
    status = Column(Enum(JobStatus), default=JobStatus.pending)
    
    # Timing
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    
    # Result
    error_message = Column(Text, nullable=True)
    quality_score = Column(Float, nullable=True)   # 0.0 to 1.0

    # Externally assigned job ID (reserved for future use)
    rq_job_id = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    source = relationship("Source", back_populates="jobs")
    evidence = relationship("Evidence", back_populates="job")


# ─────────────────────────────────────────────────────
# EVIDENCE TABLE
# Every scraped artifact: screenshot file, HTML dump, etc.
# Stored in MinIO, referenced here with its URL and hash.
# This is the "proof" of what we found at a URL at a point in time.
# ─────────────────────────────────────────────────────

class Evidence(Base):
    __tablename__ = "evidence"

    id = Column(String, primary_key=True, default=new_uuid)
    job_id = Column(String, ForeignKey("ingest_jobs.id"), nullable=False)
    type = Column(Enum(EvidenceType), nullable=False)
    
    # Where the file is stored in MinIO
    storage_uri = Column(String, nullable=False)  # e.g. "evidence/abc123.png"
    file_hash = Column(String, nullable=False)     # SHA256 of the file
    file_size_bytes = Column(Integer, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)

    job = relationship("IngestJob", back_populates="evidence")


# ─────────────────────────────────────────────────────
# DOCUMENT TABLE
# The structured output after AI extraction.
# One document per URL, with version tracking.
# ─────────────────────────────────────────────────────

class Document(Base):
    __tablename__ = "documents"

    id = Column(String, primary_key=True, default=new_uuid)
    source_id = Column(String, ForeignKey("sources.id"), nullable=False)
    url = Column(String, nullable=False)
    title = Column(String, nullable=True)
    
    # Version tracking: if we re-scrape, version increments
    doc_version = Column(Integer, default=1)
    
    # Full document content stored as Markdown (populated at ingest time)
    content_markdown = Column(Text, nullable=True)

    # Legacy S3 path (unused — kept for future use)
    content_uri = Column(String, nullable=True)

    # Quality score of extraction (0.0 to 1.0)
    quality_score = Column(Float, nullable=True)
    
    # Which strategy produced this document
    ingest_strategy = Column(Enum(IngestStrategy), nullable=True)
    
    # Hash of content for deduplication
    content_hash = Column(String, nullable=True)
    
    language = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    source = relationship("Source", back_populates="documents")
    chunks = relationship("Chunk", back_populates="document")


# ─────────────────────────────────────────────────────
# CHUNK TABLE
# A document is split into "chunks" for vector search.
# Each chunk is a paragraph or section (800 chars by default).
# ─────────────────────────────────────────────────────

class Chunk(Base):
    __tablename__ = "chunks"

    id = Column(String, primary_key=True, default=new_uuid)
    document_id = Column(String, ForeignKey("documents.id"), nullable=False)
    chunk_type = Column(Enum(ChunkType), default=ChunkType.text)
    
    # The actual text content
    text = Column(Text, nullable=False)
    
    # Position in the document
    chunk_index = Column(Integer, nullable=False)
    
    # Citation reference: points back to evidence
    citation_url = Column(String, nullable=True)
    citation_evidence_id = Column(String, ForeignKey("evidence.id"), nullable=True)
    
    # For screenshots: where in the image was this text found?
    bounding_box = Column(JSON, nullable=True)  # {"x": 10, "y": 20, "w": 300, "h": 50}
    
    # Whether this chunk has been embedded in Qdrant
    is_embedded = Column(Boolean, default=False)

    # Extended metadata
    parent_chunk_id = Column(String, ForeignKey("chunks.id"), nullable=True)
    section_path = Column(String, nullable=True)
    token_count = Column(Integer, nullable=True)
    source_method = Column(String, nullable=True)  # "html" / "rendered" / "vlm"
    language = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    document = relationship("Document", back_populates="chunks")


# ─────────────────────────────────────────────────────
# INCIDENT TABLE
# When something goes wrong during scraping (CAPTCHA, block, etc.)
# An incident is created so a human can review and resolve it.
# ─────────────────────────────────────────────────────

class Incident(Base):
    __tablename__ = "incidents"

    id = Column(String, primary_key=True, default=new_uuid)
    type = Column(Enum(IncidentType), default=IncidentType.captcha)
    source_id = Column(String, ForeignKey("sources.id"), nullable=False)
    url = Column(String, nullable=False)
    strategy = Column(Enum(IngestStrategy), nullable=True)
    severity = Column(String, default="medium")  # low, medium, high
    status = Column(Enum(IncidentStatus), default=IncidentStatus.open)
    
    # Who detected it (DOM parser, screenshot classifier, etc.)
    detector = Column(String, nullable=True)
    
    # Screenshot of the CAPTCHA page (stored in MinIO)
    evidence_screenshot_uri = Column(String, nullable=True)
    
    # Resolution info
    resolved_by = Column(String, ForeignKey("users.id"), nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    resolution_note = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    source = relationship("Source", back_populates="incidents")


# ─────────────────────────────────────────────────────
# AUDIT LOG TABLE
# Every important action is logged here.
# Who did what, when, to what object.
# Required by section 7.3 of the spec.
# ─────────────────────────────────────────────────────

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String, primary_key=True, default=new_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    action = Column(String, nullable=False)    # e.g. "LOGIN", "SOURCE_CREATED", "QUERY"
    object_type = Column(String, nullable=True) # e.g. "source", "document"
    object_id = Column(String, nullable=True)   # ID of the affected object
    extra = Column(JSON, nullable=True)      # Extra context (IP, query text, etc.)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="audit_logs")


# ─────────────────────────────────────────────────────
# EXPERIMENT TABLE
# RAG quality evaluation: retrieval metrics per query set.
# ─────────────────────────────────────────────────────

class ExperimentStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"


class Experiment(Base):
    __tablename__ = "experiments"

    id = Column(String, primary_key=True, default=new_uuid)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    created_by = Column(String, ForeignKey("users.id"), nullable=False)
    status = Column(Enum(ExperimentStatus), default=ExperimentStatus.pending)

    # Aggregated results populated after run completes
    recall_at_k = Column(Float, nullable=True)
    mrr = Column(Float, nullable=True)
    ndcg = Column(Float, nullable=True)
    avg_latency_ms = Column(Float, nullable=True)

    top_k = Column(Integer, default=5)

    created_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)

    queries = relationship("ExperimentQuery", back_populates="experiment", cascade="all, delete-orphan")


class ExperimentQuery(Base):
    __tablename__ = "experiment_queries"

    id = Column(String, primary_key=True, default=new_uuid)
    experiment_id = Column(String, ForeignKey("experiments.id"), nullable=False)
    query_text = Column(Text, nullable=False)
    expected_keywords = Column(JSON, nullable=False, default=list)  # list[str]

    # Per-query results
    recall_at_k = Column(Float, nullable=True)
    mrr = Column(Float, nullable=True)
    ndcg = Column(Float, nullable=True)
    latency_ms = Column(Float, nullable=True)
    retrieved_chunk_ids = Column(JSON, nullable=True)

    experiment = relationship("Experiment", back_populates="queries")
