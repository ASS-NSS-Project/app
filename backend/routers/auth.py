"""
routers/auth.py - Authentication and user management endpoints

Handles who can log in, what token they get, and what they are allowed to see.

Endpoints:
  GET  /auth/providers        — public; which SSO providers are configured
  POST /auth/login            — OAuth2 form login (username + password)
  POST /auth/local-login      — password-only login for the local admin UI
  GET  /auth/me               — return the current user's profile
  POST /auth/refresh          — re-issue a JWT with the latest role from DB
  GET  /auth/stats            — dashboard statistics (sources, jobs, incidents)
  GET  /auth/api-token/status — check whether the user has an API token
  POST /auth/api-token        — generate / regenerate opaque API token

Shared dependencies:
  get_authenticated_user() — used by nearly every endpoint in other routers.
  require_role(*roles)     — used by endpoints that need admin or curator access.
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
    verify_password, create_access_token, get_current_user, log_action,
    generate_api_token, ApiTokenExpiredError,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])

# OAuth2PasswordBearer extracts the "Bearer <token>" string from the
# Authorization header and passes the raw token to get_authenticated_user().
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


# --- Pydantic Schemas ---

class LoginResponse(BaseModel):
    """Response body returned for every successful login."""
    access_token: str    # the JWT or opaque token to include in future requests
    token_type: str = "bearer"
    user_id: str
    role: str
    email: str
    username: str | None


class UserResponse(BaseModel):
    """Public representation of a user (no password hash, no token hash)."""
    id: str
    username: str | None
    email: str
    full_name: str | None
    role: str
    is_active: bool

    class Config:
        from_attributes = True  # allow building from SQLAlchemy ORM instances


class LocalLoginRequest(BaseModel):
    """Request body for the local admin UI login (password only, no username)."""
    password: str


class ApiTokenResponse(BaseModel):
    """Response body when generating an API token — shown once, cannot be recovered."""
    token: str         # the raw token (store it now — we never return it again)
    expires_at: str    # ISO-8601 timestamp


class ApiTokenStatusResponse(BaseModel):
    """Tells the frontend whether the user has an active API token without revealing it."""
    has_token: bool
    expires_at: str | None
    is_expired: bool


# --- FastAPI Dependencies ---

def get_authenticated_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    FastAPI dependency: extract and validate the Bearer token, return the User.

    Accepts both JWT tokens (start with "eyJ") and opaque API tokens.
    Raises HTTP 401 if the token is invalid, expired, or not found.
    Raises HTTP 401 (with "API token expired" detail) for expired API tokens.

    Used as a dependency in every authenticated endpoint:
        current_user: User = Depends(get_authenticated_user)
    """
    try:
        user = get_current_user(token, db)
    except ApiTokenExpiredError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API token expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_role(*roles: UserRole):
    """
    FastAPI dependency factory: require the authenticated user to have one of the given roles.

    Usage:
        current_user: User = Depends(require_role(UserRole.webrag_admin, UserRole.webrag_curator))

    Returns a dependency function that returns the user if their role matches,
    or raises HTTP 403 if it doesn't. The user is also fully authenticated
    (get_authenticated_user is called first inside the returned function).
    """
    def checker(current_user: User = Depends(get_authenticated_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This action requires one of these roles: {[r.value for r in roles]}",
            )
        return current_user
    return checker


# --- Routes ---

@router.get("/providers")
def get_providers():
    """
    Public endpoint: return which SSO providers are configured on this server.

    The frontend reads this on startup to decide whether to show an
    "SSO Login" button. Returns a dict of {provider_name: bool}.
    """
    settings = get_settings()
    return {
        "keycloak": bool(settings.keycloak_client_id and settings.keycloak_url),
    }


@router.post("/login", response_model=LoginResponse)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """
    OAuth2 password form login.

    Accepts username + password as form fields (application/x-www-form-urlencoded),
    matching the OAuth2 specification. Primarily for API/script access and for
    the Swagger /docs "Authorize" button.

    Returns a JWT access token valid for JWT_EXPIRE_MINUTES (default 480 = 8 hours).
    """
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
    """
    Password-only login for the local admin account.

    Used by the Vue UI login form. There is only one local user (the admin
    bootstrapped from FIRST_ADMIN_* env vars), so we don't ask for a username —
    we find the first user with a non-null hashed_password.

    Keycloak users (hashed_password=None) cannot log in this way.
    """
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
    """
    Return the authenticated user's profile.

    Called by the frontend on startup to display the user's name and role
    in the sidebar, and to decide which menu items to show.
    """
    return current_user


@router.post("/refresh", response_model=LoginResponse)
def refresh_token(current_user: User = Depends(get_authenticated_user)):
    """
    Re-issue a JWT with the user's current role from the database.

    Called by the frontend when it detects a role mismatch between the
    stored JWT and the /me endpoint. This happens when an admin changes
    a user's role while they are logged in — the old JWT still has the old role.
    """
    token = create_access_token(current_user.id, current_user.role.value)
    return LoginResponse(access_token=token, user_id=current_user.id, role=current_user.role.value,
                         email=current_user.email, username=current_user.username)


# --- System statistics ---

@router.get("/stats")
def get_stats(
    db: Session = Depends(get_db),
    _: User = Depends(get_authenticated_user),
):
    """
    Return aggregated system statistics for the main dashboard.

    Returns:
    - Total counts: sources, jobs, open incidents, documents
    - Strategy distribution: percentage breakdown of successful scraping strategies
    - Activity chart: jobs per hour for the last 24 hours (for the bar chart)
    """
    # Count completed jobs grouped by strategy to show which strategies are used most
    strategy_counts = dict(
        db.query(IngestJob.strategy_used, func.count(IngestJob.id))
        .filter(IngestJob.strategy_used.isnot(None), IngestJob.status == "done")
        .group_by(IngestJob.strategy_used)
        .all()
    )
    strategy_total = sum(strategy_counts.values()) or 1  # avoid division by zero
    strategy_distribution = {
        k.value: round(v / strategy_total * 100) for k, v in strategy_counts.items()
    }

    # Build hourly job counts for the last 24 hours (for the activity bar chart)
    twenty_four_hours_ago = datetime.utcnow() - timedelta(hours=24)
    hourly_jobs_raw = (
        db.query(func.date_trunc('hour', IngestJob.created_at), func.count(IngestJob.id))
        .filter(IngestJob.created_at >= twenty_four_hours_ago)
        .group_by(func.date_trunc('hour', IngestJob.created_at))
        .order_by(func.date_trunc('hour', IngestJob.created_at))
        .all()
    )
    # Convert datetime objects to "HH:00" strings for the frontend chart
    activity_24h = [{"hour": d.strftime('%H:00'), "count": c} for d, c in hourly_jobs_raw]

    return {
        "sources":               db.query(Source).count(),
        "jobs":                  db.query(IngestJob).count(),
        "incidents":             db.query(Incident).filter(Incident.status == IncidentStatus.open).count(),
        "documents":             db.query(Document).count(),
        "strategy_distribution": strategy_distribution,
        "activity_24h":          activity_24h,
    }


# --- API token management ---

@router.get("/api-token/status", response_model=ApiTokenStatusResponse)
def get_api_token_status(current_user: User = Depends(get_authenticated_user)):
    """
    Return whether the current user has an API token and when it expires.

    Does NOT return the token value itself — the raw token is only shown once
    at generation time and cannot be recovered afterward.
    """
    if not current_user.api_token_hash:
        return ApiTokenStatusResponse(has_token=False, expires_at=None, is_expired=False)
    is_expired = (
        current_user.api_token_expires_at is not None
        and current_user.api_token_expires_at < datetime.utcnow()
    )
    return ApiTokenStatusResponse(
        has_token=True,
        expires_at=current_user.api_token_expires_at.isoformat() if current_user.api_token_expires_at else None,
        is_expired=is_expired,
    )


@router.post("/api-token", response_model=ApiTokenResponse)
def create_api_token(
    current_user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db),
):
    """
    Generate (or replace) the current user's long-lived opaque API token.

    The raw token is returned exactly once and is not stored in the DB
    (only its SHA-256 hash is stored). If the user loses it, they must
    generate a new one, which invalidates the previous token.
    """
    token = generate_api_token(current_user, db)
    log_action(db, current_user.id, "API_TOKEN_GENERATED")
    logger.info("API token generated", extra={"event": "api_token_generated", "user_id": current_user.id})
    return ApiTokenResponse(
        token=token,
        expires_at=current_user.api_token_expires_at.isoformat(),
    )
