"""
routers/auth_google.py - Google OAuth2 login

How OAuth2 works (simplified):
────────────────────────────────────────────────────────────────
1. User clicks "Sign in with Google"
2. Frontend calls GET /auth/google
3. Backend generates a "state" token (random string to prevent CSRF attacks)
   and redirects the user to the Google login page
4. User signs in on Google and grants access
5. Google redirects back to /auth/google/callback?code=XXX&state=YYY
6. Backend verifies the state, exchanges the "code" for an access_token with Google
7. Backend fetches the user's profile (email, name, avatar)
8. Backend creates or updates the user in our database
9. Backend issues our own JWT token
10. User is logged in ✓
────────────────────────────────────────────────────────────────

Why this approach?
- We never see the user's Google password
- Authentication is handled by Google (2FA, security, etc.)
- We only receive confirmation that "this email belongs to this user"
"""

import hmac
import hashlib
import secrets
import logging
import time
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from config import get_settings
from database import get_db
from models import User, UserRole
from services.auth_service import create_access_token

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/auth", tags=["auth-google"])

# Google OAuth2 URL constants
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

_STATE_TTL_SECONDS = 600  # state expires after 10 minutes


def _create_state() -> str:
    """Create a self-verifying HMAC-signed state token.

    Encodes a nonce + timestamp signed with JWT_SECRET so no server-side
    storage is needed — survives restarts and reloads.
    """
    nonce = secrets.token_urlsafe(16)
    ts = str(int(time.time()))
    payload = f"{nonce}:{ts}"
    sig = hmac.new(settings.jwt_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}:{sig}"


def _verify_state(state: str) -> bool:
    """Return True iff the state was created by us and is not expired."""
    try:
        nonce, ts, sig = state.rsplit(":", 2)
        payload = f"{nonce}:{ts}"
        expected = hmac.new(settings.jwt_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return False
        return (time.time() - int(ts)) <= _STATE_TTL_SECONDS
    except Exception:
        return False


@router.get("/google")
async def google_login():
    """
    Step 1: Redirect the user to the Google login page.

    We generate a random 'state' token (CSRF protection)
    and build the Google URL with parameters:
    - client_id: identifies our application
    - redirect_uri: where Google should send the user back
    - scope: what we want from Google (email and profile)
    - state: random string to verify the callback
    """
    if not settings.google_client_id:
        raise HTTPException(
            status_code=503,
            detail="Google OAuth2 is not configured. Set GOOGLE_CLIENT_ID in the .env file.",
        )

    # Generate an HMAC-signed state – verifiable without server-side storage
    state = _create_state()

    # Build the Google URL query parameters
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",        # We want an authorization code (not a token directly)
        "scope": "openid email profile", # openid = OIDC, email + profile = what we need
        "state": state,
        "access_type": "online",         # We don't need a refresh token
        "prompt": "select_account",      # Show account picker even if user is already signed in
    }

    google_url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"
    logger.info("Redirecting to Google OAuth2 login")

    return RedirectResponse(url=google_url)


@router.get("/google/callback")
async def google_callback(
    state: str,
    db: Session = Depends(get_db),
    code: str | None = None,
    error: str | None = None,
):
    """
    Steps 5–10: Google has redirected back with an authorization code.

    What happens here:
    1. Verify the state (CSRF protection)
    2. Exchange the code for an access_token with Google
    3. Fetch the user's profile
    4. Create or update the user in our DB
    5. Issue our JWT token
    6. Redirect to the frontend with the token in the URL
    """
    logger.info("OAuth callback: error=%r code_present=%s", error, code is not None)

    # User denied access on Google's side
    if error:
        logger.warning(f"Google OAuth2 error: {error}")
        return RedirectResponse(url=f"{settings.frontend_url}?auth_error={error}")

    if not code:
        logger.warning("Google OAuth2 callback received without code or error")
        raise HTTPException(status_code=400, detail="Missing authorization code")

    # Verify state – protection against CSRF
    if not _verify_state(state):
        logger.warning("Invalid or expired OAuth2 state – possible CSRF attack")
        raise HTTPException(status_code=400, detail="Invalid state parameter")
    logger.info("OAuth state OK, exchanging code with Google")

    # ── Step 2: Exchange code for access_token ────────────────────────────
    # The authorization code is one-time-use – we must exchange it promptly
    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",  # Standard OAuth2 flow
            },
        )

    if token_response.status_code != 200:
        logger.error(f"Google token endpoint returned an error: {token_response.text}")
        raise HTTPException(status_code=400, detail="Failed to obtain token from Google")

    token_data = token_response.json()
    access_token = token_data.get("access_token")

    # ── Step 3: Fetch the user's profile ─────────────────────────────────
    # Use the access token to query the Google UserInfo API
    async with httpx.AsyncClient() as client:
        userinfo_response = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )

    if userinfo_response.status_code != 200:
        logger.error(f"Google userinfo endpoint returned an error: {userinfo_response.text}")
        raise HTTPException(status_code=400, detail="Failed to fetch profile from Google")

    userinfo = userinfo_response.json()

    # Extract data from the Google profile
    google_id = userinfo.get("sub")        # "sub" = Subject = unique user ID at Google
    email = userinfo.get("email")
    full_name = userinfo.get("name")
    avatar_url = userinfo.get("picture")
    email_verified = userinfo.get("email_verified", False)

    if not email or not google_id:
        raise HTTPException(status_code=400, detail="Google did not provide an email or user ID")

    if not email_verified:
        raise HTTPException(status_code=400, detail="Email must be verified with Google")

    # ── Step 4: Create or update the user in the DB ───────────────────────
    user = _get_or_create_google_user(
        db=db,
        google_id=google_id,
        email=email,
        full_name=full_name,
        avatar_url=avatar_url,
    )

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")

    # ── Step 5: Issue our JWT token ───────────────────────────────────────
    # From this point on the user communicates with our API using this token,
    # not the Google token
    jwt_token = create_access_token(user_id=user.id, role=user.role.value)

    logger.info(f"User {email} successfully logged in via Google OAuth2")

    # ── Step 6: Redirect to the frontend with the token ───────────────────
    # Token is passed via the ?token= query parameter — main.ts reads it immediately
    # and replaces the URL via history.replaceState so the token doesn't stay in history.
    return RedirectResponse(
        url=f"{settings.frontend_url}?token={jwt_token}"
    )


def _get_or_create_google_user(
    db: Session,
    google_id: str,
    email: str,
    full_name: str | None,
    avatar_url: str | None,
) -> User:
    """
    Finds an existing user or creates a new one.

    We look up by google_id (primary) or email (fallback for users
    who previously registered with a password and now use Google).
    """
    # First look up by Google ID (most reliable – never changes)
    user = db.query(User).filter(
        User.oauth_provider == "google",
        User.oauth_id == google_id,
    ).first()

    if user:
        # Update profile in case name or avatar changed
        user.full_name = full_name or user.full_name
        user.avatar_url = avatar_url
        db.commit()
        return user

    # Fall back to email lookup – user may have registered with a password previously
    user = db.query(User).filter(User.email == email).first()
    if user:
        # Link the existing account to Google
        user.oauth_provider = "google"
        user.oauth_id = google_id
        user.avatar_url = avatar_url
        if full_name and not user.full_name:
            user.full_name = full_name
        db.commit()
        logger.info(f"Linked existing account {email} to Google OAuth2")
        return user

    # New user – create with 'user' role (lowest privilege)
    user = User(
        email=email,
        full_name=full_name,
        hashed_password=None,       # Google users don't have a local password
        oauth_provider="google",
        oauth_id=google_id,
        avatar_url=avatar_url,
        role=UserRole.user,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info(f"Created new user via Google OAuth2: {email}")
    return user
