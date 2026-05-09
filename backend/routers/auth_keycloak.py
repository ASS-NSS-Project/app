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

Security notes:
- The `state` parameter is an HMAC-signed nonce with a 10-minute TTL. This prevents
  CSRF attacks where an attacker tricks a browser into completing an OAuth flow with
  a code they control (the state value would not match).
- The access token payload is decoded WITHOUT signature verification because the
  token arrived directly from Keycloak over a TLS connection — there is no need
  to re-verify something we just received from a trusted server.
- Keycloak is the authoritative source for user roles. On every login the role is
  re-read from the 'groups' JWT claim and written to the DB, so role changes in
  Keycloak propagate automatically on the user's next login.
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

# This router extends the /auth prefix defined in auth.py. Both routers are
# registered on the same FastAPI app so /auth/keycloak and /auth/login
# share the same prefix without conflicting.
router = APIRouter(prefix="/auth", tags=["auth-keycloak"])

# A state token is valid for 10 minutes. After that the user must restart login.
# 10 minutes is generous — a typical OIDC round trip takes under 30 seconds.
_STATE_TTL_SECONDS = 600


def _oidc_base(internal: bool = False) -> str:
    """
    Return the base path for Keycloak OIDC endpoints.

    Local Docker Compose needs two URLs:
    - public URL: browser redirects to Keycloak on localhost
    - internal URL: API container exchanges the code with the keycloak service
    Production normally uses one URL for both.
    """
    base_url = settings.keycloak_internal_url if internal and settings.keycloak_internal_url else settings.keycloak_url
    return f"{base_url}/realms/{settings.keycloak_realm}/protocol/openid-connect"


def _create_state() -> str:
    """
    Generate a CSRF-resistant state parameter for the OAuth2 Authorization Code flow.

    Format: "<random_nonce>:<unix_timestamp>:<hmac_signature>"

    The nonce is 16 random bytes (URL-safe base64, 22 characters). The timestamp
    lets _verify_state() reject states older than _STATE_TTL_SECONDS without storing
    used nonces server-side (stateless validation). The HMAC ties the nonce and
    timestamp to the server's JWT secret so an attacker cannot forge a valid state.
    """
    nonce = secrets.token_urlsafe(16)    # cryptographically random, URL-safe string
    ts = str(int(time.time()))           # current epoch second as a string
    payload = f"{nonce}:{ts}"
    # HMAC-SHA256 over the payload using the server's JWT secret as the key.
    sig = hmac.new(settings.jwt_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}:{sig}"


def _verify_state(state: str) -> bool:
    """
    Verify that a state parameter was created by this server and has not expired.

    Returns False (instead of raising) so the caller can return a clean HTTP 400.
    The comparison uses hmac.compare_digest() which runs in constant time to
    prevent timing-based oracle attacks.
    """
    try:
        # Split from the right to handle nonces that contain colons (they don't,
        # but being explicit avoids surprises if the format changes later).
        nonce, ts, sig = state.rsplit(":", 2)
        payload = f"{nonce}:{ts}"
        expected = hmac.new(settings.jwt_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        # Constant-time comparison prevents an attacker from learning the correct
        # signature one bit at a time by measuring response latency.
        if not hmac.compare_digest(sig, expected):
            return False
        # Reject states older than _STATE_TTL_SECONDS — the user must restart login.
        return (time.time() - int(ts)) <= _STATE_TTL_SECONDS
    except Exception:
        # Malformed state (wrong number of colons, non-integer timestamp, etc.)
        return False


# Maps Keycloak group names to app-level UserRole enum values.
# Keycloak groups are managed in the Keycloak admin console; this mapping
# is the single place that translates them to RAG system permissions.
_GROUP_TO_ROLE: dict[str, UserRole] = {
    "admin":          UserRole.webrag_admin,   # realm admin → full RAG access
    "webrag_admin":   UserRole.webrag_admin,
    "webrag_curator": UserRole.webrag_curator,
    "webrag_analyst": UserRole.webrag_analyst,
    "webrag_user":    UserRole.webrag_user,
}


def _map_role(groups: list[str]) -> UserRole | None:
    """
    Return the highest-privilege UserRole that matches any of the user's Keycloak groups.

    Groups are checked in descending privilege order so an admin who also belongs to
    "webrag_user" gets the admin role, not the user role.
    Returns None if the user has no group recognized by this application —
    the caller should then block login with an "unauthorized" error.
    """
    for group in ("admin", "webrag_admin", "webrag_curator", "webrag_analyst", "webrag_user"):
        if group in groups:
            return _GROUP_TO_ROLE[group]
    return None


def _extract_groups(access_token: str) -> list[str]:
    """
    Decode the JWT payload section and return the 'groups' claim.

    The access token is a standard JWT (header.payload.signature). We only
    need the payload section (index 1 after splitting on "."). We do NOT verify
    the signature here because:
    - The token was just received directly from Keycloak over HTTPS.
    - We are not treating it as an auth credential — we only read claims from it.
    The group membership mapper in Keycloak must be configured to inject a
    'groups' claim into the access token for this to work.
    """
    try:
        # JWT parts are separated by "."; take the middle (payload) section.
        part = access_token.split(".")[1]
        # Base64url encoding omits padding — add "=" characters as needed to
        # make the length a multiple of 4 before decoding.
        padded = part + "=" * (-len(part) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded))
        return claims.get("groups", [])    # empty list if claim is absent
    except Exception:
        # Malformed token or unexpected claim structure — treat as no groups.
        return []


# --- Routes ---

@router.get("/keycloak")
async def keycloak_login():
    """
    Initiate the Keycloak OIDC Authorization Code login flow.

    Redirects the user's browser to the Keycloak login page. Keycloak will
    authenticate the user and redirect back to /auth/keycloak/callback with
    an authorization code and the state parameter we set here.

    Returns HTTP 503 if Keycloak is not configured (missing client ID env var),
    so the frontend can hide the SSO button when OIDC is disabled.
    """
    if not settings.keycloak_client_id:
        # Keycloak env vars are not set — SSO is disabled for this deployment.
        raise HTTPException(status_code=503, detail="Keycloak SSO is not configured.")

    # Build the Keycloak authorization URL with all required OIDC parameters.
    params = {
        "client_id": settings.keycloak_client_id,
        "redirect_uri": settings.keycloak_redirect_uri,    # where Keycloak sends the code
        "response_type": "code",                           # Authorization Code flow
        "scope": "openid email profile",                   # request basic user claims
        "state": _create_state(),                          # CSRF protection token
    }
    # HTTP 302 redirect — browser follows it to the Keycloak consent/login page.
    return RedirectResponse(url=f"{_oidc_base()}/auth?{urlencode(params)}")


@router.get("/keycloak/callback")
async def keycloak_callback(
    state: str,
    db: Session = Depends(get_db),
    code: str | None = None,
    error: str | None = None,
):
    """
    Handle the redirect back from Keycloak after the user authenticates.

    Keycloak appends ?code=...&state=... on success, or ?error=...&state=... on failure.
    This endpoint:
    1. Validates the state to prevent CSRF.
    2. Exchanges the authorization code for an access token.
    3. Fetches the user's profile from the Keycloak /userinfo endpoint.
    4. Creates or updates the user row in Postgres.
    5. Issues a local JWT and redirects to the frontend with ?token=<jwt>.

    On any error the user is redirected back to the frontend with ?auth_error=<reason>
    so the Vue app can display a meaningful error message without a bare HTTP error page.
    """
    if error:
        # Keycloak explicitly rejected the login (e.g. user cancelled the consent screen).
        logger.warning("Keycloak returned error: %s", error)
        return RedirectResponse(url=f"{settings.frontend_url}?auth_error={error}")

    if not code:
        # Keycloak should always send either 'code' or 'error' — missing both is a bug.
        raise HTTPException(status_code=400, detail="Missing authorization code")

    if not _verify_state(state):
        # State mismatch or expired — possible CSRF attempt or the user took too long.
        raise HTTPException(status_code=400, detail="Invalid or expired state")

    # --- Step 1: Exchange authorization code for tokens ---
    # The code is single-use and short-lived (typically 60 seconds in Keycloak).
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            token_resp = await client.post(
                f"{_oidc_base(internal=True)}/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": settings.keycloak_client_id,
                    "client_secret": settings.keycloak_client_secret,
                    "redirect_uri": settings.keycloak_redirect_uri,  # must match step 1 exactly
                },
            )
    except (httpx.ConnectError, httpx.TimeoutException, httpx.TransportError) as exc:
        # Network-level failures (DNS, TCP refused, TLS error, timeout).
        logger.error("Keycloak unreachable during token exchange: %s", exc,
                     extra={"event": "keycloak_connect_error"})
        raise HTTPException(status_code=503, detail="Keycloak is currently unreachable. Try again later.")

    if token_resp.status_code != 200:
        # Keycloak rejected the code — could be expired, already used, or wrong client secret.
        logger.error("Keycloak token exchange failed: %s", token_resp.text)
        raise HTTPException(status_code=400, detail="Failed to obtain token from Keycloak")

    token_data = token_resp.json()
    access_token = token_data["access_token"]    # JWT containing group claims

    # --- Step 2: Fetch the user's profile from /userinfo ---
    # /userinfo returns standard OIDC claims (sub, email, name) for the authenticated user.
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            userinfo_resp = await client.get(
                f"{_oidc_base(internal=True)}/userinfo",
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
    sub = userinfo.get("sub")          # stable unique user ID in Keycloak (UUID-like string)
    email = userinfo.get("email")      # user's email address
    full_name = userinfo.get("name")   # display name from Keycloak profile

    if not sub or not email:
        # Both claims are required — without them we cannot create a DB row.
        raise HTTPException(status_code=400, detail="Keycloak did not return email or sub claim")

    # --- Step 3: Map Keycloak groups to a UserRole ---
    # Groups come from the access token (not /userinfo) because the group membership
    # protocol mapper in Keycloak must be configured to inject them into the access token.
    keycloak_roles = _extract_groups(access_token)
    role = _map_role(keycloak_roles)

    if role is None:
        # The user authenticated successfully in Keycloak but belongs to no group
        # recognized by this application — treat as unauthorized.
        logger.warning(
            "Keycloak login blocked — no recognized group for %s (groups=%s)", email, keycloak_roles,
            extra={"event": "keycloak_unauthorized", "email": email},
        )
        log_action(db, None, "LOGIN_FAILED", None, None,
                   {"source": "keycloak", "email": email, "reason": "no_recognized_group"})
        return RedirectResponse(url=f"{settings.frontend_url}?auth_error=unauthorized")

    # --- Step 4: Create or update the user in Postgres ---
    user = _get_or_create_keycloak_user(db, sub, email, full_name, role)

    if not user.is_active:
        # Account exists but has been manually deactivated by an admin.
        log_action(db, user.id, "LOGIN_FAILED", "user", user.id,
                   {"source": "keycloak", "reason": "account_deactivated"})
        raise HTTPException(status_code=403, detail="Account is deactivated")

    # --- Step 5: Issue a local JWT and redirect to the frontend ---
    log_action(db, user.id, "LOGIN", "user", user.id, {"source": "keycloak", "role": role.value})
    jwt_token = create_access_token(user_id=user.id, role=user.role.value)
    logger.info(
        "User %s logged in via Keycloak (role=%s)", email, role.value,
        extra={"event": "login_success", "source": "keycloak", "user_id": user.id, "role": role.value},
    )

    # The frontend's main.ts reads the ?token= query parameter on load and stores
    # the JWT in localStorage, then removes the parameter from the URL.
    return RedirectResponse(url=f"{settings.frontend_url}?token={jwt_token}")


def _get_or_create_keycloak_user(
    db: Session,
    keycloak_sub: str,
    email: str,
    full_name: str | None,
    role: UserRole,
) -> User:
    """
    Find the User row for this Keycloak identity, creating it if it does not exist.

    Three lookup paths in priority order:

    1. Match by (oauth_provider="keycloak", oauth_id=sub) — the normal path for
       returning users. The Keycloak sub is stable even if the user changes their email.

    2. Match by email — handles the case where the user previously logged in with
       a local password and is now linking their account to Keycloak SSO. We write
       the oauth_provider and oauth_id so future logins use path 1.

    3. Create a new User row — first time this Keycloak user logs in.

    In all cases, `role` is written to the DB unconditionally so that role changes
    in Keycloak take effect on the next login.
    """
    # Primary lookup: use the Keycloak sub (stable across email changes in Keycloak).
    user = db.query(User).filter(
        User.oauth_provider == "keycloak",
        User.oauth_id == keycloak_sub,
    ).first()

    if user:
        # Returning Keycloak user — sync role and display name in case an admin
        # changed them in Keycloak since the last login.
        user.role = role
        user.full_name = full_name or user.full_name   # don't clear a name with None
        db.commit()
        return user

    # Fallback: look up by email to link an existing local account.
    user = db.query(User).filter(User.email == email).first()
    if user:
        # Existing account found — attach the Keycloak identity to it.
        user.oauth_provider = "keycloak"
        user.oauth_id = keycloak_sub
        user.role = role
        if full_name and not user.full_name:
            # Only fill in the name if the account didn't already have one.
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

    # No existing account — create a new one. hashed_password=None marks it as
    # an SSO-only account that cannot log in via /auth/local-login.
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
    db.refresh(user)    # populate user.id after the INSERT
    log_action(db, user.id, "USER_CREATED", "user", user.id,
               {"source": "keycloak", "email": email, "role": role.value})
    logger.info(
        "Created new user via Keycloak: %s (role=%s)", email, role.value,
        extra={"event": "user_registered", "source": "keycloak", "user_id": user.id, "role": role.value},
    )
    return user
