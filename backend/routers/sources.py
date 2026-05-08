"""
routers/sources.py - Source and ingest job management endpoints

A "source" is a web URL that the system monitors and periodically scrapes.
This router handles the full lifecycle of sources and their associated ingest jobs.

SSRF protection:
All URLs submitted by users pass through _validate_url() before being stored
or scraped. This blocks attempts to make the server fetch internal/private
addresses (e.g. http://169.254.169.254/ — AWS metadata endpoint, or
http://postgres:5432/ — the database). We check both literal IP addresses
and resolved hostnames.

Endpoints:
  GET  /sources/pipeline/stats    — queue depth and error rate for the pipeline monitor
  GET  /sources/                  — list active sources with document counts
  POST /sources/                  — create a new source (admin/curator only)
  PATCH /sources/{id}             — update source name, strategy, or frequency
  POST /sources/{id}/ingest       — manually trigger an ingest job
  GET  /sources/jobs/all          — list all ingest jobs (with source name)
  POST /sources/jobs/{id}/cancel  — cancel a pending or running job
  DELETE /sources/jobs/{id}       — permanently delete a finished job record
  GET  /sources/{id}/jobs         — list jobs for a specific source
  DELETE /sources/{id}            — soft-delete (deactivate) a source
"""
import ipaddress
import logging
import socket
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, timedelta
from database import get_db
from models import Source, IngestJob, JobStatus, IngestStrategy, UserRole, User, Document
from routers.auth import get_authenticated_user, require_role
from services.auth import log_action
from services.queue import publish_job

logger = logging.getLogger(__name__)

# These CIDR ranges are private/internal addresses that the scraper must never fetch.
# Allowing them would let an attacker use the server as a proxy to reach internal services.
_PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),         # RFC 1918 private range
    ipaddress.ip_network("172.16.0.0/12"),       # RFC 1918 private range
    ipaddress.ip_network("192.168.0.0/16"),      # RFC 1918 private range
    ipaddress.ip_network("127.0.0.0/8"),         # loopback
    ipaddress.ip_network("169.254.0.0/16"),      # link-local / AWS EC2 metadata endpoint
    ipaddress.ip_network("::1/128"),             # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),            # IPv6 unique local
]


def _validate_url(url: str) -> str:
    """
    SSRF guard: reject non-HTTP(S) schemes and private/internal IP addresses.

    Two-stage check:
    1. If the URL host is a literal IP address: check it directly against _PRIVATE_NETS.
    2. If the URL host is a hostname: resolve it with DNS and check every resolved address.
       This prevents attacks like "localhost.attacker.com" pointing to 127.0.0.1.

    Args:
        url: The URL string to validate.

    Returns:
        The original url if valid.

    Raises:
        HTTPException 400: If the scheme is not http/https, the host is missing,
                           the host resolves to a private address, or DNS fails.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="URL must use http or https")
    host = parsed.hostname
    if not host:
        raise HTTPException(status_code=400, detail="Invalid URL: missing host")
    try:
        # Try to parse as a literal IP address first
        addr = ipaddress.ip_address(host)
        if any(addr in net for net in _PRIVATE_NETS):
            raise HTTPException(status_code=400, detail="URL points to a private/internal address")
    except ValueError:
        # Host is a domain name — resolve it and check every resulting IP
        try:
            resolved = socket.getaddrinfo(host, None)
            for *_, sockaddr in resolved:
                addr = ipaddress.ip_address(sockaddr[0])
                if any(addr in net for net in _PRIVATE_NETS):
                    raise HTTPException(status_code=400, detail="URL resolves to a private/internal address")
        except socket.gaierror:
            raise HTTPException(status_code=400, detail="URL host could not be resolved")
    return url


router = APIRouter(prefix="/sources", tags=["Sources"])


# --- Pydantic Schemas ---

class SourceCreate(BaseModel):
    """Fields required to create a new source."""
    name: str
    base_url: str
    permission_type: str = "public"
    permission_ref: Optional[str] = None              # e.g. URL to the robots.txt or permission doc
    preferred_strategy: IngestStrategy = IngestStrategy.html
    crawl_frequency_hours: int = 24                   # how often the scheduler re-crawls this source
    crawl_depth: int = 1
    rate_limit_rps: float = 1.0                       # requests per second (polite crawling)
    retention_days_evidence: int = 90                 # how long to keep screenshots/HTML in S3


class SourceResponse(BaseModel):
    """Public representation of a source, including a computed document count."""
    id: str
    name: str
    base_url: str
    permission_type: str
    preferred_strategy: str
    crawl_frequency_hours: int
    is_active: bool
    created_at: datetime
    last_crawled_at: Optional[datetime] = None
    doc_count: int = 0   # computed from a JOIN, not a DB column

    class Config:
        from_attributes = True


class IngestTriggerRequest(BaseModel):
    """Optional URL override for a manual ingest trigger (defaults to source.base_url)."""
    url: Optional[str] = None


class JobResponse(BaseModel):
    """Public representation of one ingest job."""
    id: str
    url: str
    status: str
    strategy_used: Optional[str]
    quality_score: Optional[float]
    error_message: Optional[str]
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# --- Routes ---

@router.get("/pipeline/stats")
def get_pipeline_stats(
    db: Session = Depends(get_db),
    _: User = Depends(get_authenticated_user),
):
    """
    Return live pipeline queue stats for the pipeline monitor widget.

    - pending: jobs waiting in the RabbitMQ queue to be picked up
    - running: jobs actively being processed by a worker
    - error_rate_24h: percentage of jobs in the last 24h that failed or were CAPTCHA-blocked
    """
    pending = db.query(IngestJob).filter(IngestJob.status == JobStatus.pending).count()
    running = db.query(IngestJob).filter(IngestJob.status == JobStatus.running).count()
    since = datetime.utcnow() - timedelta(hours=24)
    total_24h = db.query(IngestJob).filter(IngestJob.created_at >= since).count()
    failed_24h = db.query(IngestJob).filter(
        IngestJob.created_at >= since,
        IngestJob.status.in_([JobStatus.failed, JobStatus.captcha_blocked]),
    ).count()
    error_rate = round(failed_24h / total_24h * 100, 1) if total_24h else 0.0
    return {"pending": pending, "running": running, "error_rate_24h": error_rate}


@router.get("/", response_model=list[SourceResponse])
def list_sources(
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_authenticated_user),
):
    """
    List all active sources, newest first, with their document counts.

    The document count is computed with a single GROUP BY query rather than N+1
    queries (one per source), then merged into the result list.
    """
    sources = (
        db.query(Source)
        .filter(Source.is_active == True)
        .order_by(Source.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    source_ids = [s.id for s in sources]
    # One query to get all document counts at once
    doc_counts = (
        dict(
            db.query(Document.source_id, func.count(Document.id))
            .filter(Document.source_id.in_(source_ids))
            .group_by(Document.source_id)
            .all()
        )
        if source_ids
        else {}
    )
    result = []
    for s in sources:
        # Build a plain dict because Pydantic's from_attributes cannot read extra
        # computed attributes (like doc_count) set on a SQLAlchemy ORM instance —
        # they are not mapped columns and are silently ignored.
        d = {c.name: getattr(s, c.name) for c in s.__table__.columns}
        d["doc_count"] = doc_counts.get(s.id, 0)
        result.append(d)
    return result


@router.post("/", response_model=SourceResponse)
def create_source(
    request: SourceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.webrag_admin, UserRole.webrag_curator)),
):
    """
    Create a new monitored source.

    Only admins and curators can add sources — analysts and plain users
    are read-only. The URL is SSRF-validated before saving.
    """
    _validate_url(str(request.base_url))
    source = Source(
        name=request.name,
        base_url=str(request.base_url),
        permission_type=request.permission_type,
        permission_ref=request.permission_ref,
        preferred_strategy=request.preferred_strategy,
        crawl_frequency_hours=request.crawl_frequency_hours,
        crawl_depth=request.crawl_depth,
        rate_limit_rps=request.rate_limit_rps,
        retention_days_evidence=request.retention_days_evidence,
        created_by=current_user.id,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    log_action(db, current_user.id, "SOURCE_CREATED", "source", source.id,
               {"name": source.name, "url": source.base_url})
    logger.info("Source created", extra={
        "event": "source_created", "source_id": source.id,
        "source_name": source.name, "url": source.base_url,
        "user_id": current_user.id,
    })
    return source


class SourceUpdate(BaseModel):
    """Fields that can be changed on an existing source (all optional)."""
    name: Optional[str] = None
    preferred_strategy: Optional[IngestStrategy] = None
    crawl_frequency_hours: Optional[int] = None
    is_active: Optional[bool] = None


@router.patch("/{source_id}", response_model=SourceResponse)
def update_source(
    source_id: str,
    request: SourceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.webrag_admin, UserRole.webrag_curator)),
):
    """
    Update one or more fields on an existing source.

    Only provided (non-None) fields are changed — this is a PATCH, not a PUT.
    """
    source = db.query(Source).filter(Source.id == source_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    if request.name is not None:
        source.name = request.name
    if request.preferred_strategy is not None:
        source.preferred_strategy = request.preferred_strategy
    if request.crawl_frequency_hours is not None:
        source.crawl_frequency_hours = request.crawl_frequency_hours
    if request.is_active is not None:
        source.is_active = request.is_active
    db.commit()
    db.refresh(source)
    log_action(db, current_user.id, "SOURCE_UPDATED", "source", source_id,
               {"fields": request.model_dump(exclude_none=True)})
    logger.info("Source updated", extra={
        "event": "source_updated", "source_id": source_id,
        "fields": request.model_dump(exclude_none=True), "user_id": current_user.id,
    })
    return source


@router.post("/{source_id}/ingest", response_model=JobResponse)
def trigger_ingest(
    source_id: str,
    request: IngestTriggerRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.webrag_admin, UserRole.webrag_curator)),
):
    """
    Manually trigger an immediate ingest job for a source.

    Creates an IngestJob row with status "pending" and publishes its ID to the
    "ingest" RabbitMQ queue. The ingest worker picks it up asynchronously.

    The optional url field overrides the source's base_url — useful for testing
    a specific sub-page without changing the source permanently.
    """
    source = db.query(Source).filter(Source.id == source_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    # SSRF-validate the URL (either the override or the source's own URL)
    url = _validate_url(request.url or source.base_url)

    job = IngestJob(
        source_id=source_id,
        url=url,
        status=JobStatus.pending,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    try:
        publish_job(job.id)
    except Exception as e:
        logger.error("Failed to publish job %s to queue: %s", job.id, e)
        job.status = JobStatus.failed
        job.error_message = f"Failed to publish to queue: {e}"
        db.commit()
        raise HTTPException(status_code=500, detail="Failed to queue job")

    log_action(db, current_user.id, "INGEST_TRIGGERED", "job", job.id, {"url": url})
    logger.info("Ingest job queued", extra={
        "event": "ingest_triggered", "job_id": job.id,
        "source_id": source_id, "url": url, "user_id": current_user.id,
    })
    return job


class JobResponseWithSource(JobResponse):
    """Extended job response that also includes the source name and base URL."""
    source_name: Optional[str] = None
    source_base_url: Optional[str] = None

    class Config:
        from_attributes = True


@router.get("/jobs/all", response_model=list[JobResponseWithSource])
def list_all_jobs(
    source_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_authenticated_user),
):
    """
    List all ingest jobs across all sources, with their source names.

    Used by the pipeline monitor to show a full job history table.
    Can be filtered by source_id or status.
    """
    q = db.query(IngestJob, Source.name, Source.base_url).join(
        Source, IngestJob.source_id == Source.id
    )
    if source_id:
        q = q.filter(IngestJob.source_id == source_id)
    if status:
        q = q.filter(IngestJob.status == status)
    rows = q.order_by(IngestJob.created_at.desc()).offset(offset).limit(limit).all()
    result = []
    for job, src_name, src_url in rows:
        # Same plain-dict workaround as list_sources: JOIN columns can't be set as
        # ORM attributes and read back by Pydantic's from_attributes.
        d = {c.name: getattr(job, c.name) for c in job.__table__.columns}
        d["source_name"] = src_name
        d["source_base_url"] = src_url
        result.append(d)
    return result


@router.post("/jobs/{job_id}/cancel")
def cancel_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.webrag_admin, UserRole.webrag_curator)),
):
    """
    Cancel a pending or running ingest job.

    Sets status to "failed" with error_message "Cancelled by user".
    The worker may have already picked up the job — if so it will still run
    to completion but the result won't be used (the job is marked failed).
    There is no mechanism to interrupt a running worker mid-scrape.
    """
    job = db.query(IngestJob).filter(IngestJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in (JobStatus.pending, JobStatus.running):
        raise HTTPException(status_code=400, detail="Only pending or running jobs can be cancelled")
    job.status = JobStatus.failed
    job.error_message = "Cancelled by user"
    db.commit()
    log_action(db, current_user.id, "JOB_CANCELLED", "job", job_id)
    logger.info("Job cancelled", extra={"event": "job_cancelled", "job_id": job_id, "user_id": current_user.id})
    return {"message": "Job cancelled"}


@router.delete("/jobs/{job_id}")
def delete_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.webrag_admin)),
):
    """
    Permanently delete a finished ingest job record.

    Only terminal jobs (failed, done, captcha_blocked) can be deleted.
    Pending or running jobs must be cancelled first to avoid leaving orphaned
    workers with no associated job record to update.
    """
    job = db.query(IngestJob).filter(IngestJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status in (JobStatus.pending, JobStatus.running):
        raise HTTPException(status_code=400, detail="Cancel the job before deleting it")
    db.delete(job)
    db.commit()
    log_action(db, current_user.id, "JOB_DELETED", "job", job_id)
    logger.info("Job deleted", extra={"event": "job_deleted", "job_id": job_id, "user_id": current_user.id})
    return {"message": "Job deleted"}


@router.get("/{source_id}/jobs", response_model=list[JobResponse])
def list_jobs(
    source_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_authenticated_user),
):
    """Return the 50 most recent ingest jobs for a specific source."""
    return (
        db.query(IngestJob)
        .filter(IngestJob.source_id == source_id)
        .order_by(IngestJob.created_at.desc())
        .limit(50)
        .all()
    )


@router.delete("/{source_id}")
def delete_source(
    source_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.webrag_admin)),
):
    """
    Soft-delete (deactivate) a source.

    Sets is_active=False instead of deleting the row. This preserves the
    source's history (documents, chunks, audit logs) while stopping the
    scheduler from creating new crawl jobs for it.
    """
    source = db.query(Source).filter(Source.id == source_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    source.is_active = False
    db.commit()
    log_action(db, current_user.id, "SOURCE_DELETED", "source", source_id)
    logger.info("Source deactivated", extra={
        "event": "source_deleted", "source_id": source_id, "user_id": current_user.id,
    })
    return {"message": "Source deactivated"}
