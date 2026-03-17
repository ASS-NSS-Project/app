from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime
import redis
from rq import Queue

from database import get_db
from models import Source, IngestJob, JobStatus, IngestStrategy, UserRole, User
from routers.auth import get_authenticated_user, require_role
from services.auth_service import log_action
from config import get_settings

settings = get_settings()
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

    url = request.url or source.base_url

    job = IngestJob(
        source_id=source_id,
        url=url,
        status=JobStatus.pending,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    try:
        rq_conn = redis.from_url(settings.redis_url)
        q = Queue("ingest", connection=rq_conn)
        rq_job = q.enqueue(
            "worker.process_ingest_job",
            job.id,
            job_timeout=300,
        )
        job.rq_job_id = rq_job.id
        db.commit()
    except Exception as e:
        job.status = JobStatus.failed
        job.error_message = f"Failed to queue job: {e}"
        db.commit()
        raise HTTPException(status_code=500, detail=f"Failed to queue job: {e}")

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
