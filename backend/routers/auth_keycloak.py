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
from services.auth_service import create_access_token

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
# "analytic" is the Keycloak group name; our enum value is "analyst".
_GROUP_TO_ROLE: dict[str, UserRole] = {
    "admin":    UserRole.admin,
    "curator":  UserRole.curator,
    "analytic": UserRole.analyst,  # Keycloak group is "analytic", app role is "analyst"
    "user":     UserRole.user,
}


def _map_role(groups: list[str]) -> UserRole:
    """Highest-privilege matching group wins. Defaults to 'user'."""
    for group in ("admin", "curator", "analytic", "user"):
        if group in groups:
            return _GROUP_TO_ROLE[group]
    return UserRole.user


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

    user = _get_or_create_keycloak_user(db, sub, email, full_name, role)

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")

    jwt_token = create_access_token(user_id=user.id, role=user.role.value)
    logger.info("User %s logged in via Keycloak (role=%s)", email, role.value)

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
        logger.info("Linked existing account %s to Keycloak", email)
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
    logger.info("Created new user via Keycloak: %s (role=%s)", email, role.value)
    return user
