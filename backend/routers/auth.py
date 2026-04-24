"""
routers/auth.py - Authentication Endpoints

POST /auth/login  → returns JWT token
POST /auth/register → creates a new user (admin only)
GET  /auth/me     → returns current user info
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import Optional

from database import get_db

logger = logging.getLogger(__name__)
from models import User, UserRole, AuditLog, Source, IngestJob, Document, Incident, IncidentStatus
from services.auth_service import (
    verify_password, create_access_token, get_current_user,
    hash_password, log_action
)

router = APIRouter(prefix="/auth", tags=["Authentication"])

# OAuth2PasswordBearer extracts the token from the Authorization header.
# When you send "Authorization: Bearer <token>", this extracts the token.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


# ── Pydantic schemas (request/response shapes) ────────────────────

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    role: str
    email: str
    username: str | None


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=64)
    email: str = Field(..., max_length=254)
    password: str = Field(..., min_length=12, max_length=128)
    full_name: str = Field("", max_length=128)
    role: UserRole = UserRole.user


class UserResponse(BaseModel):
    id: str
    username: str | None
    email: str
    full_name: str | None
    role: str
    is_active: bool

    class Config:
        from_attributes = True


# ── Dependency: get current authenticated user ────────────────────

def get_authenticated_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    FastAPI dependency: inject the current user into any route.
    
    Usage:
        @router.get("/protected")
        def my_route(current_user: User = Depends(get_authenticated_user)):
            ...
    """
    user = get_current_user(token, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_role(*roles: UserRole):
    """
    Role-based access control dependency factory.
    
    Usage:
        @router.post("/admin-only")
        def admin_route(user: User = Depends(require_role(UserRole.admin))):
            ...
    """
    def checker(current_user: User = Depends(get_authenticated_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This action requires one of these roles: {[r.value for r in roles]}",
            )
        return current_user
    return checker


# ── Routes ───────────────────────────────────────────────────────

@router.post("/login", response_model=LoginResponse)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """
    Login with email + password, get a JWT token back.
    
    The token must be sent in all subsequent requests:
    Authorization: Bearer <token>
    """
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        logger.warning("Login failed", extra={"event": "login_failed", "username": form_data.username})
        log_action(db, None, "LOGIN_FAILED", extra={"username": form_data.username})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    token = create_access_token(user.id, user.role.value)
    log_action(db, user.id, "LOGIN")
    logger.info("Login successful", extra={"event": "login_success", "user_id": user.id, "role": user.role.value})

    return LoginResponse(
        access_token=token,
        user_id=user.id,
        role=user.role.value,
        email=user.email,
        username=user.username,
    )


@router.post("/register", response_model=UserResponse)
def register(
    request: RegisterRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Create a new user. Admin only."""
    if db.query(User).filter(User.email == request.email).first():
        logger.warning("Register failed: email already exists", extra={
            "event": "register_failed", "email": request.email,
        })
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        username=request.username,
        email=request.email,
        hashed_password=hash_password(request.password),
        full_name=request.full_name,
        role=request.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    log_action(db, current_user.id, "USER_CREATED", "user", user.id)
    logger.info("User registered", extra={"event": "user_registered", "user_id": user.id, "role": user.role.value})
    return user


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_authenticated_user)):
    """Get the currently logged-in user's info."""
    return current_user


# ── System statistics overview ─────────────────────────────────────

@router.get("/stats")
def get_stats(
    db: Session = Depends(get_db),
    _: User = Depends(get_authenticated_user),
):
    """
    Returns basic system statistics for the dashboard.
    One query instead of N+1 calls from the frontend.
    """
    return {
        "sources":   db.query(Source).count(),
        "jobs":      db.query(IngestJob).count(),
        "incidents": db.query(Incident).filter(Incident.status == IncidentStatus.open).count(),
        "documents": db.query(Document).count(),
    }


# ── Audit log ──────────────────────────────────────────────────────

class AuditLogEntry(BaseModel):
    id: str
    action: str
    object_type: str | None
    object_id: str | None
    extra: dict | None
    created_at: str
    user_email: str | None

    class Config:
        from_attributes = True


@router.get("/audit", response_model=list[AuditLogEntry])
def get_audit_log(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin, UserRole.curator)),
):
    """
    Returns audit log entries ordered from newest to oldest.
    Accessible only to admins and curators.
    """
    rows = (
        db.query(AuditLog)
        .order_by(AuditLog.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    result = []
    for row in rows:
        # Look up the user's email (may be None for system actions)
        user_email = None
        if row.user_id:
            user = db.query(User).filter(User.id == row.user_id).first()
            user_email = user.email if user else None
        result.append(AuditLogEntry(
            id=row.id,
            action=row.action,
            object_type=row.object_type,
            object_id=row.object_id,
            extra=row.extra,
            created_at=row.created_at.isoformat() if row.created_at else "",
            user_email=user_email,
        ))
    return result


# ── User management ───────────────────────────────────────────────

@router.get("/users", response_model=list[UserResponse])
def list_users(
    db: Session = Depends(get_db),
    _: User = Depends(require_role(UserRole.admin, UserRole.curator)),
):
    """Returns all users. Accessible to admins and curators."""
    return db.query(User).order_by(User.created_at.desc()).all()


class UserUpdate(BaseModel):
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None


@router.patch("/users/{user_id}", response_model=UserResponse)
def update_user(
    user_id: str,
    request: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Updates a user's role or active status. Admin only."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if request.role is not None:
        user.role = request.role
    if request.is_active is not None:
        user.is_active = request.is_active
    db.commit()
    db.refresh(user)
    log_action(db, current_user.id, "USER_UPDATED", "user", user_id,
               request.model_dump(exclude_none=True))
    return user
