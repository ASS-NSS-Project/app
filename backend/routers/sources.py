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
from services.auth_service import log_action
from services.queue_service import publish_job

logger = logging.getLogger(__name__)

_PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local / AWS metadata
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]


def _validate_url(url: str) -> str:
    """Reject non-HTTP(S) schemes and private/loopback IP addresses (SSRF guard)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="URL must use http or https")
    host = parsed.hostname
    if not host:
        raise HTTPException(status_code=400, detail="Invalid URL: missing host")
    try:
        addr = ipaddress.ip_address(host)
        if any(addr in net for net in _PRIVATE_NETS):
            raise HTTPException(status_code=400, detail="URL points to a private/internal address")
    except ValueError:
        # hostname — resolve and check
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


class SourceCreate(BaseModel):
    name: str
    base_url: str
    permission_type: str = "public"
    permission_ref: Optional[str] = None
    preferred_strategy: IngestStrategy = IngestStrategy.html
    crawl_frequency_hours: int = 24
    crawl_depth: int = 1
    rate_limit_rps: float = 1.0
    retention_days_evidence: int = 90


class SourceResponse(BaseModel):
    id: str
    name: str
    base_url: str
    permission_type: str
    preferred_strategy: str
    crawl_frequency_hours: int
    is_active: bool
    created_at: datetime
    last_crawled_at: Optional[datetime] = None
    doc_count: int = 0

    class Config:
        from_attributes = True


class IngestTriggerRequest(BaseModel):
    url: Optional[str] = None


class JobResponse(BaseModel):
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


@router.get("/pipeline/stats")
def get_pipeline_stats(
    db: Session = Depends(get_db),
    _: User = Depends(get_authenticated_user),
):
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
    sources = (
        db.query(Source)
        .filter(Source.is_active == True)
        .order_by(Source.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    source_ids = [s.id for s in sources]
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
        d = {c.name: getattr(s, c.name) for c in s.__table__.columns}
        d["doc_count"] = doc_counts.get(s.id, 0)
        result.append(d)
    return result


@router.post("/", response_model=SourceResponse)
def create_source(
    request: SourceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.curator)),
):
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
    name: Optional[str] = None
    preferred_strategy: Optional[IngestStrategy] = None
    crawl_frequency_hours: Optional[int] = None
    is_active: Optional[bool] = None


@router.patch("/{source_id}", response_model=SourceResponse)
def update_source(
    source_id: str,
    request: SourceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.curator)),
):
    # Look up the source by ID, return 404 if not found
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
    current_user: User = Depends(require_role(UserRole.admin, UserRole.curator)),
):
    source = db.query(Source).filter(Source.id == source_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

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
        d = {c.name: getattr(job, c.name) for c in job.__table__.columns}
        d["source_name"] = src_name
        d["source_base_url"] = src_url
        result.append(d)
    return result


@router.post("/jobs/{job_id}/cancel")
def cancel_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.curator)),
):
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
    current_user: User = Depends(require_role(UserRole.admin)),
):
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
    current_user: User = Depends(require_role(UserRole.admin)),
):
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
