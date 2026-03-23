import ipaddress
import logging
import socket
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime
from database import get_db
from models import Source, IngestJob, JobStatus, IngestStrategy, UserRole, User
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

    class Config:
        from_attributes = True


@router.get("/", response_model=list[SourceResponse])
def list_sources(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_authenticated_user),
):
    return db.query(Source).filter(Source.is_active == True).all()


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
    return job


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
    return {"message": "Source deactivated"}
