"""
services/auth_service.py - Authentication and Authorization

We use JWT (JSON Web Tokens) for authentication.

How login works:
1. User sends email + password
2. We check password hash in DB
3. If correct, we create a JWT token (a signed string that encodes the user's ID)
4. User sends this token with every future request
5. We verify the token's signature to confirm it's legitimate

This is stateless - no session storage needed on the server.
"""

from datetime import datetime, timedelta
from typing import Optional

import logging

from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from config import get_settings
from models import User, UserRole, AuditLog, Source, IngestStrategy

logger = logging.getLogger(__name__)
settings = get_settings()

# CryptContext handles password hashing.
# bcrypt is a strong hashing algorithm - it's slow by design (makes brute-force hard)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Convert a plain password to a bcrypt hash for storage."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str | None) -> bool:
    """
    Checks whether a plain-text password matches the stored hash.
    Returns False if the user has no password (logs in via OAuth).
    """
    if not hashed_password:
        # OAuth user – no local password, cannot log in this way
        return False
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(user_id: str, role: str) -> str:
    """
    Create a JWT token for a user.
    
    The token contains:
    - sub: user ID (the "subject")
    - role: user's role (for authorization)
    - exp: expiry timestamp
    
    The token is signed with JWT_SECRET, so we can verify it wasn't tampered with.
    """
    expire = datetime.utcnow() + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {
        "sub": user_id,
        "role": role,
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> Optional[dict]:
    """
    Decode and verify a JWT token.
    Returns the payload dict, or None if invalid/expired.
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
        return payload
    except JWTError as e:
        logger.warning("JWT decode failed: %s", e, extra={"event": "jwt_invalid"})
        return None


def get_current_user(token: str, db: Session) -> Optional[User]:
    """
    Get the User object for a given JWT token.
    Returns None if token is invalid or user doesn't exist.
    """
    payload = decode_token(token)
    if not payload:
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    return db.query(User).filter(User.id == user_id, User.is_active == True).first()


def log_action(
    db: Session,
    user_id: Optional[str],
    action: str,
    object_type: str = None,
    object_id: str = None,
    extra: dict = None,
):
    """
    Write an entry to the audit log.
    
    Call this for any important action:
    - LOGIN, LOGOUT
    - SOURCE_CREATED, SOURCE_DELETED
    - INGEST_TRIGGERED
    - QUERY_EXECUTED
    - INCIDENT_RESOLVED
    """
    log = AuditLog(
        user_id=user_id,
        action=action,
        object_type=object_type,
        object_id=object_id,
        extra=extra or {},
    )
    db.add(log)
    db.commit()


def ensure_admin_exists(db: Session):
    """
    Create the first admin user on system startup if none exists.
    This ensures there's always at least one admin to log in with.
    """
    existing = db.query(User).filter(User.role == UserRole.webrag_admin).first()
    if not existing:
        admin = User(
            username=settings.first_admin_username,
            email=settings.first_admin_email,
            hashed_password=hash_password(settings.first_admin_password),
            full_name="System Administrator",
            role=UserRole.webrag_admin,
        )
        db.add(admin)
        db.commit()
        logger.info("Created initial admin user: %s", settings.first_admin_email,
                    extra={"event": "admin_created"})
    elif existing.username is None:
        existing.username = settings.first_admin_username
        db.commit()
        logger.info("Backfilled username for admin user: %s", settings.first_admin_email,
                    extra={"event": "admin_username_backfilled"})


def ensure_default_sources(db: Session) -> None:
    if not settings.default_source_urls:
        return
    for entry in settings.default_source_urls.split(","):
        parts = entry.strip().split("|")
        url = parts[0].strip()
        if not url:
            continue
        strategy_str = parts[1].strip() if len(parts) > 1 else "html"
        try:
            strategy = IngestStrategy(strategy_str)
        except ValueError:
            logger.warning("Unknown strategy '%s' for %s, defaulting to html", strategy_str, url)
            strategy = IngestStrategy.html
        if not db.query(Source).filter(Source.base_url == url).first():
            db.add(Source(
                name=url,
                base_url=url,
                permission_type="public",
                preferred_strategy=strategy,
                crawl_frequency_hours=24,
                is_active=True,
            ))
            logger.info("Seeded default source: %s (%s)", url, strategy.value,
                        extra={"event": "source_seeded", "url": url, "strategy": strategy.value})
    db.commit()
