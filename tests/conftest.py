import sys
import os

# Put the backend package directory on sys.path so that backend-internal imports
# (e.g. `from config import get_settings`, `from models import ...`) resolve the
# same module objects that main.py and the routers use.  Without this, importing
# `from backend.config import ...` in tests would create a *second* copy of the
# module, breaking lru_cache singletons and causing AttributeErrors on settings.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from main import app  # noqa: E402


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://127.0.0.1:8000",
    ) as c:
        yield c


@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient):
    """Return Authorization headers for the default admin account."""
    from config import get_settings

    settings = get_settings()
    resp = await client.post(
        "/auth/login",
        data={
            "username": settings.first_admin_email,
            "password": settings.first_admin_password,
        },
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
