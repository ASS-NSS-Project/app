"""
routers/auth_keycloak.py - Keycloak OIDC login

Flow (standard Authorization Code):
  1. User clicks "Sign in with SSO"
  2. GET /auth/keycloak  → redirect to Keycloak auth page
  3. User authenticates with Keycloak
  4. Keycloak redirects to /auth/keycloak/callback?code=...&state=...
  5. Backend exchanges code for tokens at Keycloak token endpoint
  6. Backend reads realm roles from the access token claims
  7. Backend creates / updates the user in DB with the Keycloak-assigned role
  8. Backend issues its own JWT, redirects to the frontend with ?token=
"""

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from config import get_settings
from database import get_db
from models import User, UserRole
from services.auth import create_access_token, log_action

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/auth", tags=["auth-keycloak"])

_STATE_TTL_SECONDS = 600


def _oidc_base() -> str:
    return f"{settings.keycloak_url}/realms/{settings.keycloak_realm}/protocol/openid-connect"


def _create_state() -> str:
    nonce = secrets.token_urlsafe(16)
    ts = str(int(time.time()))
    payload = f"{nonce}:{ts}"
    sig = hmac.new(settings.jwt_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}:{sig}"


def _verify_state(state: str) -> bool:
    try:
        nonce, ts, sig = state.rsplit(":", 2)
        payload = f"{nonce}:{ts}"
        expected = hmac.new(settings.jwt_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return False
        return (time.time() - int(ts)) <= _STATE_TTL_SECONDS
    except Exception:
        return False


# Keycloak group name → app UserRole.
_GROUP_TO_ROLE: dict[str, UserRole] = {
    "admin":       UserRole.rag_admin,   # realm admin → full RAG access
    "rag_admin":   UserRole.rag_admin,
    "rag_curator": UserRole.rag_curator,
    "rag_analyst": UserRole.rag_analyst,
    "rag_user":    UserRole.rag_user,
}


def _map_role(groups: list[str]) -> UserRole | None:
    """Highest-privilege matching group wins. Returns None if user has no recognized group."""
    for group in ("admin", "rag_admin", "rag_curator", "rag_analyst", "rag_user"):
        if group in groups:
            return _GROUP_TO_ROLE[group]
    return None


def _extract_groups(access_token: str) -> list[str]:
    """Decode JWT payload (no sig check — token came directly from Keycloak).
    Reads the 'groups' claim injected by the group membership protocol mapper."""
    try:
        part = access_token.split(".")[1]
        padded = part + "=" * (-len(part) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded))
        return claims.get("groups", [])
    except Exception:
        return []


@router.get("/keycloak")
async def keycloak_login():
    if not settings.keycloak_client_id:
        raise HTTPException(status_code=503, detail="Keycloak SSO is not configured.")

    params = {
        "client_id": settings.keycloak_client_id,
        "redirect_uri": settings.keycloak_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": _create_state(),
    }
    return RedirectResponse(url=f"{_oidc_base()}/auth?{urlencode(params)}")


@router.get("/keycloak/callback")
async def keycloak_callback(
    state: str,
    db: Session = Depends(get_db),
    code: str | None = None,
    error: str | None = None,
):
    if error:
        logger.warning("Keycloak returned error: %s", error)
        return RedirectResponse(url=f"{settings.frontend_url}?auth_error={error}")

    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    if not _verify_state(state):
        raise HTTPException(status_code=400, detail="Invalid or expired state")

    # Exchange code for tokens
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            token_resp = await client.post(
                f"{_oidc_base()}/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": settings.keycloak_client_id,
                    "client_secret": settings.keycloak_client_secret,
                    "redirect_uri": settings.keycloak_redirect_uri,
                },
            )
    except (httpx.ConnectError, httpx.TimeoutException, httpx.TransportError) as exc:
        logger.error("Keycloak unreachable during token exchange: %s", exc,
                     extra={"event": "keycloak_connect_error"})
        raise HTTPException(status_code=503, detail="Keycloak is currently unreachable. Try again later.")

    if token_resp.status_code != 200:
        logger.error("Keycloak token exchange failed: %s", token_resp.text)
        raise HTTPException(status_code=400, detail="Failed to obtain token from Keycloak")

    token_data = token_resp.json()
    access_token = token_data["access_token"]

    # Fetch user info
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            userinfo_resp = await client.get(
                f"{_oidc_base()}/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
    except (httpx.ConnectError, httpx.TimeoutException, httpx.TransportError) as exc:
        logger.error("Keycloak unreachable during userinfo fetch: %s", exc,
                     extra={"event": "keycloak_connect_error"})
        raise HTTPException(status_code=503, detail="Keycloak is currently unreachable. Try again later.")

    if userinfo_resp.status_code != 200:
        logger.error("Keycloak userinfo failed: %s", userinfo_resp.text)
        raise HTTPException(status_code=400, detail="Failed to fetch user info from Keycloak")

    userinfo = userinfo_resp.json()
    sub = userinfo.get("sub")
    email = userinfo.get("email")
    full_name = userinfo.get("name")

    if not sub or not email:
        raise HTTPException(status_code=400, detail="Keycloak did not return email or sub claim")

    keycloak_roles = _extract_groups(access_token)
    role = _map_role(keycloak_roles)

    if role is None:
        logger.warning(
            "Keycloak login blocked — no recognized group for %s (groups=%s)", email, keycloak_roles,
            extra={"event": "keycloak_unauthorized", "email": email},
        )
        log_action(db, None, "LOGIN_FAILED", None, None,
                   {"source": "keycloak", "email": email, "reason": "no_recognized_group"})
        return RedirectResponse(url=f"{settings.frontend_url}?auth_error=unauthorized")

    user = _get_or_create_keycloak_user(db, sub, email, full_name, role)

    if not user.is_active:
        log_action(db, user.id, "LOGIN_FAILED", "user", user.id,
                   {"source": "keycloak", "reason": "account_deactivated"})
        raise HTTPException(status_code=403, detail="Account is deactivated")

    log_action(db, user.id, "LOGIN", "user", user.id, {"source": "keycloak", "role": role.value})
    jwt_token = create_access_token(user_id=user.id, role=user.role.value)
    logger.info(
        "User %s logged in via Keycloak (role=%s)", email, role.value,
        extra={"event": "login_success", "source": "keycloak", "user_id": user.id, "role": role.value},
    )

    return RedirectResponse(url=f"{settings.frontend_url}?token={jwt_token}")


def _get_or_create_keycloak_user(
    db: Session,
    keycloak_sub: str,
    email: str,
    full_name: str | None,
    role: UserRole,
) -> User:
    # Primary lookup: Keycloak sub (stable across email changes)
    user = db.query(User).filter(
        User.oauth_provider == "keycloak",
        User.oauth_id == keycloak_sub,
    ).first()

    if user:
        # Keycloak is source of truth for roles — sync on every login
        user.role = role
        user.full_name = full_name or user.full_name
        db.commit()
        return user

    # Fallback: link existing account by email
    user = db.query(User).filter(User.email == email).first()
    if user:
        user.oauth_provider = "keycloak"
        user.oauth_id = keycloak_sub
        user.role = role
        if full_name and not user.full_name:
            user.full_name = full_name
        db.commit()
        db.refresh(user)
        log_action(db, user.id, "USER_UPDATED", "user", user.id,
                   {"action": "keycloak_linked", "email": email})
        logger.info(
            "Linked existing account %s to Keycloak", email,
            extra={"event": "user_updated", "action": "keycloak_linked", "user_id": user.id},
        )
        return user

    # New user
    user = User(
        email=email,
        full_name=full_name,
        hashed_password=None,
        oauth_provider="keycloak",
        oauth_id=keycloak_sub,
        role=role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    log_action(db, user.id, "USER_CREATED", "user", user.id,
               {"source": "keycloak", "email": email, "role": role.value})
    logger.info(
        "Created new user via Keycloak: %s (role=%s)", email, role.value,
        extra={"event": "user_registered", "source": "keycloak", "user_id": user.id, "role": role.value},
    )
    return user
