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
def run_migrations():
    """Run Alembic migrations once before the test suite (synchronous, idempotent)."""
    from alembic.config import Config as AlembicConfig
    from alembic import command as alembic_command

    alembic_cfg = AlembicConfig(os.path.join(_BACKEND, "alembic.ini"))
    alembic_cfg.set_main_option("script_location", os.path.join(_BACKEND, "alembic"))
    alembic_command.upgrade(alembic_cfg, "head")


@pytest.fixture(scope="session", autouse=True)
def create_admin(run_migrations):
    """Ensure the admin user exists (created by ensure_admin_exists on first run)."""
    from database import SessionLocal
    from services.auth_service import ensure_admin_exists

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
