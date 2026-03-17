from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime

from database import get_db
from models import User, Incident, UserRole
from routers.auth import get_authenticated_user, require_role
from services.captcha_service import CaptchaService
from services.auth_service import log_action

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
    resolution_note: str


@router.get("/", response_model=list[IncidentResponse])
def list_incidents(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_authenticated_user),
):
    q = db.query(Incident)
    if status:
        q = q.filter(Incident.status == status)
    return q.order_by(Incident.created_at.desc()).limit(100).all()


@router.post("/{incident_id}/resolve", response_model=IncidentResponse)
def resolve_incident(
    incident_id: str,
    request: ResolveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.curator)),
):
    service = CaptchaService(db)
    try:
        incident = service.resolve_incident(
            incident_id=incident_id,
            resolver_user_id=current_user.id,
            resolution_note=request.resolution_note,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    log_action(db, current_user.id, "INCIDENT_RESOLVED", "incident", incident_id)
    return incident
