"""
routers/incidents.py - CAPTCHA incident management endpoints

When the ingest worker hits a CAPTCHA or bot-detection page it cannot bypass,
it creates an Incident record and pauses crawling that URL. Admins and curators
can list these incidents, resolve them (with a note explaining what was done),
and optionally trigger a retry crawl automatically.

Endpoints:
  POST /incidents/simulate          — create a fake incident for testing (admin only)
  GET  /incidents/                  — list incidents, optionally filtered by status
  POST /incidents/{id}/resolve      — mark an incident resolved and queue a retry job

Incident lifecycle:
  open → in_progress (optional manual step) → resolved

When an incident is resolved, the endpoint automatically creates a new IngestJob
for the affected URL so the crawler retries it — no manual source re-ingest needed.
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import Optional, Literal
from datetime import datetime

# Module-level logger; name follows the Python module path for easy Loki queries.
logger = logging.getLogger(__name__)

from database import get_db
from models import User, Incident, IncidentType, IncidentStatus, IngestStrategy, Source, UserRole
from routers.auth import get_authenticated_user, require_role
from services.captcha import CaptchaService
from services.auth import log_action
from services.queue import publish_job

# All routes here are grouped under /incidents in the OpenAPI spec.
router = APIRouter(prefix="/incidents", tags=["Incidents"])


# --- Pydantic Schemas ---

class IncidentResponse(BaseModel):
    """Public representation of one Incident row returned by list and resolve endpoints."""
    id: str
    type: str              # IncidentType enum value, e.g. "captcha"
    source_id: str         # which monitored source triggered this incident
    url: str               # the specific URL that was blocked
    severity: str          # "low", "medium", or "high"
    status: str            # IncidentStatus: "open", "in_progress", or "resolved"
    detector: Optional[str]                   # which detection method fired (e.g. "keyword", "simulate")
    evidence_screenshot_uri: Optional[str]    # S3 path to the screenshot taken when blocked
    created_at: datetime
    resolved_at: Optional[datetime]           # None until the incident is resolved
    resolution_note: Optional[str]            # free-text explanation written by the resolver

    class Config:
        # Allow SQLAlchemy ORM instances to be passed directly to this schema.
        from_attributes = True


class ResolveRequest(BaseModel):
    """Request body for POST /incidents/{id}/resolve — requires a non-empty explanation."""
    resolution_note: str = Field(..., min_length=1, max_length=2000)


class SimulateRequest(BaseModel):
    """
    Request body for POST /incidents/simulate — creates a synthetic incident.

    If source_id is omitted the endpoint picks the first active source in the DB.
    The defaults produce a mid-severity incident against a dummy URL.
    """
    source_id: Optional[str] = None
    url: str = "https://example.com/captcha-test"
    severity: Literal["low", "medium", "high"] = "medium"
    detector: str = "simulate"    # tag shown in the incident list so it's obvious this is fake


# --- Routes ---

@router.post("/simulate", response_model=IncidentResponse)
def simulate_incident(
    request: SimulateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.webrag_admin)),
):
    """
    Create a synthetic CAPTCHA incident for testing the incident management UI.

    Only webrag_admin may use this endpoint — it writes to the DB and would
    create spurious data if called by non-admin users. The created incident
    looks identical to a real one so the frontend can be tested end-to-end
    without triggering an actual scrape failure.
    """
    # Resolve which source to attach the simulated incident to.
    source_id = request.source_id
    if source_id:
        # If the caller specified a source_id, make sure it actually exists.
        if not db.query(Source).filter(Source.id == source_id).first():
            raise HTTPException(status_code=404, detail="Source not found")
    else:
        # No source_id provided — pick any active source so the incident has a valid FK.
        first = db.query(Source).filter(Source.is_active == True).first()
        if not first:
            # Cannot create an incident without at least one source in the DB.
            raise HTTPException(status_code=400, detail="No active sources — create one first")
        source_id = first.id

    # Build the Incident ORM object. strategy=html because that is the strategy
    # most likely to hit a CAPTCHA in real use (plain HTTP fetch, no JS rendering).
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
    db.refresh(incident)    # refresh so `incident.id` is populated by Postgres

    # Write an immutable audit record so admins can see who created simulated incidents.
    log_action(db, current_user.id, "INCIDENT_SIMULATED", "incident", incident.id)
    logger.info(
        "Simulated incident %s created by %s", incident.id, current_user.email,
        extra={"event": "incident_simulated", "incident_id": incident.id, "user_id": current_user.id},
    )
    return incident


@router.get("/", response_model=list[IncidentResponse])
def list_incidents(
    status: Optional[str] = None,
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_authenticated_user),
):
    """
    Return a paginated list of incidents, newest first.

    Pass ?status=open to see only open incidents (the most common dashboard view).
    Omit status to see all incidents regardless of resolution state.
    """
    q = db.query(Incident)
    if status:
        # Filter by the string value of the IncidentStatus enum column.
        q = q.filter(Incident.status == status)
    # Newest first so the dashboard shows the most recent problem at the top.
    return q.order_by(Incident.created_at.desc()).offset(offset).limit(limit).all()


@router.post("/{incident_id}/resolve", response_model=IncidentResponse)
def resolve_incident(
    incident_id: str,
    request: ResolveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.webrag_admin, UserRole.webrag_curator)),
):
    """
    Mark an incident as resolved and automatically queue a retry crawl job.

    The resolution_note is required so there is always a human-readable record
    of what was done (e.g. "Cleared cookies, site accessible again").

    After resolving, if the source is still active, a new IngestJob is created
    and published to RabbitMQ so the worker retries the blocked URL without
    requiring a manual re-ingest from the sources page.

    Raises HTTP 404 if the incident does not exist (CaptchaService raises ValueError).
    """
    # CaptchaService.resolve_incident sets status=resolved, records resolved_at and
    # resolution_note, and returns the updated Incident object.
    service = CaptchaService(db)
    try:
        incident = service.resolve_incident(
            incident_id=incident_id,
            resolver_user_id=current_user.id,
            resolution_note=request.resolution_note,
        )
    except ValueError as e:
        # CaptchaService raises ValueError when the incident_id is not found.
        logger.warning("resolve_incident failed: %s", e)
        raise HTTPException(status_code=404, detail="Incident not found")

    # Write audit log BEFORE the retry job so the log order reflects the user intent.
    log_action(db, current_user.id, "INCIDENT_RESOLVED", "incident", incident_id)
    logger.info(
        "Incident %s resolved by %s", incident_id, current_user.email,
        extra={"event": "incident_resolved", "incident_id": incident_id, "user_id": current_user.id},
    )

    # Automatically retry the URL that was blocked.
    # We only queue if the source is still active — if it was deactivated while
    # the incident was open, there is no point crawling it again.
    source = db.query(Source).filter(Source.id == incident.source_id).first()
    if source and source.is_active:
        # IngestJob and JobStatus are imported here to avoid a circular import at
        # module load time (models imports nothing from routers, but this import path
        # is safe because we only reach it at runtime inside a request handler).
        from models import IngestJob, JobStatus
        retry_job = IngestJob(
            source_id=incident.source_id,
            url=incident.url,
            status=JobStatus.pending,
        )
        db.add(retry_job)
        db.commit()
        db.refresh(retry_job)    # populate retry_job.id before publishing
        try:
            # Publish the job ID to RabbitMQ. The ingest worker will pick it up
            # and attempt to scrape the URL again using the strategy waterfall.
            publish_job(retry_job.id)
            logger.info("Queued retry job %s for incident %s", retry_job.id, incident_id)
        except Exception as exc:
            # Publishing can fail if RabbitMQ is temporarily down. We log a warning
            # but do NOT roll back the incident resolution — the resolution was
            # successful; the retry can be triggered again manually from the sources page.
            logger.warning("Failed to queue retry job for incident %s: %s", incident_id, exc)

    return incident
