"""
Test configuration and shared fixtures.

These tests run against the real FastAPI app using an in-process ASGI
transport (no network), but they still require the services defined in
.env to be reachable (PostgreSQL, etc.).  For CI, the workflow spins up
those services as GitHub Actions service containers.

To run locally:
    pip install pytest pytest-asyncio httpx
    pytest tests/
"""

import pytest_asyncio
from httpx import AsyncClient, ASGITransport

# Import after env is loaded so config picks up test overrides
from backend.main import app  # type: ignore[import]


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
    from backend.config import get_settings  # type: ignore[import]

    settings = get_settings()
    resp = await client.post(
        "/auth/login",
        data={
            "username": settings.admin_email,
            "password": settings.admin_password,
        },
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
