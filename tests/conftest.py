"""
Shared pytest fixtures for backend integration tests

- Backend import-path bootstrap so tests resolve the same modules as runtime
- Session-scoped database schema bootstrap (`Base.metadata.create_all`)
- Session-scoped default admin creation used by authenticated endpoint tests
- Async HTTP client fixture bound to the FastAPI ASGI app
- Reusable `auth_headers` fixture with a valid Bearer token for the default admin

NOT a test module; This is Pytest Infrastructure which is consumed by the other test files
"""
import sys
import os
# Put the backend package directory on sys.path so that backend-internal imports
# (e.g. `from config import get_settings`) resolve the same module objects that
# main.py and the routers use at runtime.
_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, _BACKEND)

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

@pytest.fixture(scope="session", autouse=True)
def create_schema():
    """Create all tables once before the test suite."""
    from database import Base, engine
    import models  # noqa: F401 — registers all ORM classes with Base

    Base.metadata.create_all(bind=engine)

@pytest.fixture(scope="session", autouse=True)
def create_admin(create_schema):
    """Ensure the admin user exists (created by ensure_admin_exists on first run)."""
    from database import SessionLocal
    from services.auth import ensure_admin_exists

    db = SessionLocal()
    try:
        ensure_admin_exists(db)

    finally:
        db.close()

@pytest_asyncio.fixture
async def client(create_admin):
    # ASGITransport does not call the ASGI lifespan — migrations and admin user
    # are already handled by the session-scoped fixtures above.
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://127.0.0.1:8000") as c:
        yield c

@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient):
    """Return Authorization headers for the default admin account."""
    from config import get_settings

    s = get_settings()

    resp = await client.post(
        "/auth/login",
        data={"username": s.first_admin_username, "password": s.first_admin_password},
    )

    assert resp.status_code == 200, resp.text

    return {"Authorization": f"Bearer {resp.json()['access_token']}"}
