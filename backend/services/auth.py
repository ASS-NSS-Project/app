"""
services/auth.py - Authentication and Authorisation

Handles everything related to who can log in and what they are allowed to do.

Authentication answers "who are you?":
- Local login: email + password checked against a bcrypt hash in the DB
- JWT: a signed token that encodes the user's ID and role, issued on login
- Opaque API token: a long random string for programmatic access (scripts, CI)

Authorisation answers "are you allowed to do this?" — enforced in routers via
role checks against the UserRole enum.

JWT flow:
1. POST /auth/login with email + password
2. Server verifies password hash, issues a JWT (signed with JWT_SECRET)
3. Client stores JWT, sends it as `Authorization: Bearer <token>` on every request
4. Server decodes + verifies the JWT signature on each request (stateless — no DB lookup)

Opaque API token flow:
1. POST /auth/token/generate — server generates a random token, stores its SHA-256 hash
2. Client sends the raw token in `Authorization: Bearer <token>` just like a JWT
3. Server hashes the incoming token and looks it up in the users table
"""

import hashlib
import secrets
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

# CryptContext wraps bcrypt password hashing.
# bcrypt is intentionally slow (controlled by its "cost factor") to make brute-force
# and rainbow-table attacks impractical even if the hashed passwords are leaked.
# deprecated="auto" automatically re-hashes old entries if the algorithm is changed.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """
    Hash a plain-text password using bcrypt.

    Args:
        password: The plain-text password to hash.

    Returns:
        A bcrypt hash string suitable for storage in the database.
        The hash includes the salt, so no separate salt column is needed.
    """
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str | None) -> bool:
    """
    Check whether a plain-text password matches the stored bcrypt hash.

    Args:
        plain_password: The password the user typed.
        hashed_password: The hash stored in the database. None for OAuth-only users.

    Returns:
        True if the password matches, False otherwise.
        Always returns False if hashed_password is None (OAuth users have no local password).
    """
    if not hashed_password:
        return False  # OAuth user — they must log in via Google or Keycloak, not a password
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(user_id: str, role: str) -> str:
    """
    Create and sign a JWT access token for a user.

    The token payload contains:
    - sub: the user's UUID (standard JWT "subject" claim)
    - role: the user's role (used for authorisation in routers)
    - exp: expiry timestamp (UTC, unix epoch seconds)

    The token is signed with HMAC-SHA256 using JWT_SECRET.
    Anyone who modifies the payload will have an invalid signature and be rejected.

    Args:
        user_id: UUID string of the authenticated user.
        role: UserRole value (e.g. "webrag_admin").

    Returns:
        A compact JWT string (three base64url segments separated by dots).
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

    Verifies the signature against JWT_SECRET and checks that the token has not expired.

    Args:
        token: A JWT string from an Authorization header.

    Returns:
        The decoded payload dict (containing "sub", "role", "exp") if valid.
        None if the token is invalid, expired, or tampered with.
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


class ApiTokenExpiredError(Exception):
    """Raised by get_current_user() when an opaque API token is recognised but past its expiry."""


def _hash_api_token(token: str) -> str:
    """
    SHA-256 hash of a raw opaque API token for safe storage.
    We never store the raw token — only this hash — so a DB leak cannot be used directly.
    """
    return hashlib.sha256(token.encode()).hexdigest()


def generate_api_token(user: User, db: Session) -> str:
    """
    Generate (or replace) a user's long-lived opaque API token.

    Generates a cryptographically random URL-safe string, stores its SHA-256 hash
    in the user row, and returns the raw token. The raw token is shown only once —
    it cannot be recovered later (only replaced by generating a new one).

    Args:
        user: The User ORM object to attach the token to.
        db: Active database session.

    Returns:
        The raw token string. The caller must show this to the user immediately.
    """
    token = secrets.token_urlsafe(32)  # 32 bytes = 256 bits of entropy
    user.api_token_hash       = _hash_api_token(token)
    user.api_token_created_at = datetime.utcnow()
    user.api_token_expires_at = datetime.utcnow() + timedelta(hours=settings.api_token_expire_hours)
    db.commit()
    db.refresh(user)
    return token


def get_current_user(token: str, db: Session) -> Optional[User]:
    """
    Resolve a bearer token string to an active User object.

    Accepts both JWT tokens and opaque API tokens in the same function so
    routers don't need to know which type they received.

    Detection: JWTs always start with "eyJ" (base64url of `{"alg":...}`).
    Everything else is treated as an opaque API token.

    Args:
        token: The raw token string from the Authorization header.
        db: Active database session.

    Returns:
        The matching active User, or None if the token is invalid/unknown.

    Raises:
        ApiTokenExpiredError: If the token is a recognised API token that has passed its expiry.
    """
    if token.startswith("eyJ"):
        # JWT path: decode the token and look up the user by the embedded user ID
        payload = decode_token(token)
        if not payload:
            return None
        user_id = payload.get("sub")
        if not user_id:
            return None
        return db.query(User).filter(User.id == user_id, User.is_active == True).first()

    # Opaque API token path: hash the incoming token and match against stored hashes
    token_hash = _hash_api_token(token)
    user = db.query(User).filter(
        User.api_token_hash == token_hash,
        User.is_active == True,
    ).first()
    if not user:
        return None
    if user.api_token_expires_at and user.api_token_expires_at < datetime.utcnow():
        raise ApiTokenExpiredError()
    return user


def log_action(
    db: Session,
    user_id: Optional[str],
    action: str,
    object_type: str = None,
    object_id: str = None,
    extra: dict = None,
):
    """
    Write an immutable entry to the audit_logs table.

    Call this for every significant action so admins can audit who did what and when.
    Common action values: LOGIN, LOGOUT, SOURCE_CREATED, SOURCE_DELETED,
    INGEST_TRIGGERED, QUERY_EXECUTED, INCIDENT_RESOLVED, USER_ROLE_CHANGED.

    Args:
        db: Active database session.
        user_id: UUID of the user who performed the action. None for system actions.
        action: Short uppercase verb describing what happened.
        object_type: The type of resource affected (e.g. "source", "incident").
        object_id: UUID of the affected resource.
        extra: Arbitrary JSON-serialisable dict for additional context (IP, query text, etc.).
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
    Bootstrap the first admin user if none exists in the database.

    Called on every API startup. The check is a no-op if an admin already exists,
    so it is safe to run repeatedly without creating duplicate accounts.

    Also backfills the username field on the admin account if it was created
    before the username column was added (migration 0002).

    The admin credentials are read from FIRST_ADMIN_* environment variables.
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
        # Backfill: admin was created before the username column existed
        existing.username = settings.first_admin_username
        db.commit()
        logger.info("Backfilled username for admin user: %s", settings.first_admin_email,
                    extra={"event": "admin_username_backfilled"})


def ensure_default_sources(db: Session) -> None:
    """
    Seed default sources from the DEFAULT_SOURCE_URLS environment variable.

    Only adds sources that don't already exist (matched by base_url).
    Format: comma-separated "url|strategy" pairs, e.g.:
        https://mendelu.cz|html,https://example.com|rendered

    If strategy is omitted, defaults to "html".
    Called once on API startup — safe to run repeatedly.

    Args:
        db: Active database session.
    """
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

        # Skip if a source with this URL already exists
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
