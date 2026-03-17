"""
routers/auth.py - Authentication Endpoints

POST /auth/login  → returns JWT token
POST /auth/register → creates a new user (admin only)
GET  /auth/me     → returns current user info
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from database import get_db
from models import User, UserRole
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


class RegisterRequest(BaseModel):
    email: str
    password: str
    full_name: str = ""
    role: UserRole = UserRole.user


class UserResponse(BaseModel):
    id: str
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
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        log_action(db, None, "LOGIN_FAILED", extra={"email": form_data.username})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    token = create_access_token(user.id, user.role.value)
    log_action(db, user.id, "LOGIN")

    return LoginResponse(
        access_token=token,
        user_id=user.id,
        role=user.role.value,
        email=user.email,
    )


@router.post("/register", response_model=UserResponse)
def register(
    request: RegisterRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.admin)),
):
    """Create a new user. Admin only."""
    if db.query(User).filter(User.email == request.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=request.email,
        hashed_password=hash_password(request.password),
        full_name=request.full_name,
        role=request.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    log_action(db, current_user.id, "USER_CREATED", "user", user.id)
    return user


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_authenticated_user)):
    """Get the currently logged-in user's info."""
    return current_user
