"""
routers/auth.py - Authentication Endpoints

POST /auth/local-login → password-only login for the local admin account
POST /auth/login       → OAuth2 form login (username + password, for API/script access)
GET  /auth/me          → current user info
POST /auth/refresh     → re-issue JWT with current DB role
GET  /auth/providers   → which SSO providers are configured
GET  /auth/stats       → system statistics for the dashboard
"""

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from config import get_settings
from database import get_db

logger = logging.getLogger(__name__)
from models import User, UserRole, Source, IngestJob, Document, Incident, IncidentStatus
from services.auth import (
    verify_password, create_access_token, get_current_user, log_action
)

router = APIRouter(prefix="/auth", tags=["Authentication"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


# ── Schemas ───────────────────────────────────────────────────────

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    role: str
    email: str
    username: str | None


class UserResponse(BaseModel):
    id: str
    username: str | None
    email: str
    full_name: str | None
    role: str
    is_active: bool

    class Config:
        from_attributes = True


class LocalLoginRequest(BaseModel):
    password: str


# ── Dependencies ──────────────────────────────────────────────────

def get_authenticated_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    user = get_current_user(token, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_role(*roles: UserRole):
    def checker(current_user: User = Depends(get_authenticated_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This action requires one of these roles: {[r.value for r in roles]}",
            )
        return current_user
    return checker


# ── Routes ────────────────────────────────────────────────────────

@router.get("/providers")
def get_providers():
    """Public — tells the frontend which SSO providers are configured."""
    settings = get_settings()
    return {
        "keycloak": bool(settings.keycloak_client_id and settings.keycloak_url),
    }


@router.post("/login", response_model=LoginResponse)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """OAuth2 form login (username + password). For API/script access."""
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        logger.warning("Login failed", extra={"event": "login_failed", "username": form_data.username})
        log_action(db, None, "LOGIN_FAILED", extra={"username": form_data.username})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect password")

    token = create_access_token(user.id, user.role.value)
    log_action(db, user.id, "LOGIN")
    logger.info("Login successful", extra={"event": "login_success", "user_id": user.id, "role": user.role.value})
    return LoginResponse(access_token=token, user_id=user.id, role=user.role.value,
                         email=user.email, username=user.username)


@router.post("/local-login", response_model=LoginResponse)
def local_login(
    request: LocalLoginRequest,
    db: Session = Depends(get_db),
):
    """Password-only login for the local admin account. Used by the UI login form."""
    user = db.query(User).filter(User.hashed_password.isnot(None)).first()
    if not user or not verify_password(request.password, user.hashed_password):
        logger.warning("Local login failed", extra={"event": "login_failed"})
        log_action(db, None, "LOGIN_FAILED", extra={"source": "local"})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect password")

    token = create_access_token(user.id, user.role.value)
    log_action(db, user.id, "LOGIN")
    logger.info("Local login successful", extra={"event": "login_success", "user_id": user.id})
    return LoginResponse(access_token=token, user_id=user.id, role=user.role.value,
                         email=user.email, username=user.username)


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_authenticated_user)):
    """Current user info."""
    return current_user


@router.post("/refresh", response_model=LoginResponse)
def refresh_token(current_user: User = Depends(get_authenticated_user)):
    """Re-issue JWT with current DB role. Called by frontend on role mismatch."""
    token = create_access_token(current_user.id, current_user.role.value)
    return LoginResponse(access_token=token, user_id=current_user.id, role=current_user.role.value,
                         email=current_user.email, username=current_user.username)


# ── System statistics ─────────────────────────────────────────────

@router.get("/stats")
def get_stats(
    db: Session = Depends(get_db),
    _: User = Depends(get_authenticated_user),
):
    """System statistics for the dashboard."""
    strategy_counts = dict(
        db.query(IngestJob.strategy_used, func.count(IngestJob.id))
        .filter(IngestJob.strategy_used.isnot(None), IngestJob.status == "done")
        .group_by(IngestJob.strategy_used)
        .all()
    )
    strategy_total = sum(strategy_counts.values()) or 1
    strategy_distribution = {
        k.value: round(v / strategy_total * 100) for k, v in strategy_counts.items()
    }

    twenty_four_hours_ago = datetime.utcnow() - timedelta(hours=24)
    hourly_jobs_raw = (
        db.query(func.date_trunc('hour', IngestJob.created_at), func.count(IngestJob.id))
        .filter(IngestJob.created_at >= twenty_four_hours_ago)
        .group_by(func.date_trunc('hour', IngestJob.created_at))
        .order_by(func.date_trunc('hour', IngestJob.created_at))
        .all()
    )
    activity_24h = [{"hour": d.strftime('%H:00'), "count": c} for d, c in hourly_jobs_raw]

    return {
        "sources":                db.query(Source).count(),
        "jobs":                   db.query(IngestJob).count(),
        "incidents":              db.query(Incident).filter(Incident.status == IncidentStatus.open).count(),
        "documents":              db.query(Document).count(),
        "strategy_distribution":  strategy_distribution,
        "activity_24h":           activity_24h,
    }
