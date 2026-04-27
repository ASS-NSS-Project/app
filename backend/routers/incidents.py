import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import Optional, Literal
from datetime import datetime

logger = logging.getLogger(__name__)

from database import get_db
from models import User, Incident, IncidentType, IncidentStatus, IngestStrategy, Source, UserRole
from routers.auth import get_authenticated_user, require_role
from services.captcha_service import CaptchaService
from services.auth_service import log_action
from services.queue_service import publish_job

router = APIRouter(prefix="/incidents", tags=["Incidents"])


class IncidentResponse(BaseModel):
    id: str
    type: str
    source_id: str
    url: str
    severity: str
    status: str
    detector: Optional[str]
    evidence_screenshot_uri: Optional[str]
    created_at: datetime
    resolved_at: Optional[datetime]
    resolution_note: Optional[str]

    class Config:
        from_attributes = True


class ResolveRequest(BaseModel):
    resolution_note: str = Field(..., min_length=1, max_length=2000)


class SimulateRequest(BaseModel):
    source_id: Optional[str] = None
    url: str = "https://example.com/captcha-test"
    severity: Literal["low", "medium", "high"] = "medium"
    detector: str = "simulate"


@router.post("/simulate", response_model=IncidentResponse)
def simulate_incident(
    request: SimulateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.rag_admin)),
):
    """Create a synthetic CAPTCHA incident for testing. Admin only."""
    source_id = request.source_id
    if source_id:
        if not db.query(Source).filter(Source.id == source_id).first():
            raise HTTPException(status_code=404, detail="Source not found")
    else:
        first = db.query(Source).filter(Source.is_active == True).first()
        if not first:
            raise HTTPException(status_code=400, detail="No active sources — create one first")
        source_id = first.id

    incident = Incident(
        type=IncidentType.captcha,
        source_id=source_id,
        url=request.url,
        strategy=IngestStrategy.html,
        severity=request.severity,
        status=IncidentStatus.open,
        detector=request.detector,
    )
    db.add(incident)
    db.commit()
    db.refresh(incident)
    log_action(db, current_user.id, "INCIDENT_SIMULATED", "incident", incident.id)
    logger.info("Simulated incident %s created by %s", incident.id, current_user.email)
    return incident


@router.get("/", response_model=list[IncidentResponse])
def list_incidents(
    status: Optional[str] = None,
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_authenticated_user),
):
    q = db.query(Incident)
    if status:
        q = q.filter(Incident.status == status)
    return q.order_by(Incident.created_at.desc()).offset(offset).limit(limit).all()


@router.post("/{incident_id}/resolve", response_model=IncidentResponse)
def resolve_incident(
    incident_id: str,
    request: ResolveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.rag_admin, UserRole.rag_curator)),
):
    service = CaptchaService(db)
    try:
        incident = service.resolve_incident(
            incident_id=incident_id,
            resolver_user_id=current_user.id,
            resolution_note=request.resolution_note,
        )
    except ValueError as e:
        logger.warning("resolve_incident failed: %s", e)
        raise HTTPException(status_code=404, detail="Incident not found")

    log_action(db, current_user.id, "INCIDENT_RESOLVED", "incident", incident_id)

    # Retry the failed URL: create a new IngestJob and publish it
    source = db.query(Source).filter(Source.id == incident.source_id).first()
    if source and source.is_active:
        from models import IngestJob, JobStatus
        retry_job = IngestJob(
            source_id=incident.source_id,
            url=incident.url,
            status=JobStatus.pending,
        )
        db.add(retry_job)
        db.commit()
        db.refresh(retry_job)
        try:
            publish_job(retry_job.id)
            logger.info("Queued retry job %s for incident %s", retry_job.id, incident_id)
        except Exception as exc:
            logger.warning("Failed to queue retry job for incident %s: %s", incident_id, exc)

    return incident
