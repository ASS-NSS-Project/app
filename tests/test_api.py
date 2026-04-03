"""
Integration tests for the RAG System API.

Each test uses the in-process ASGI client from conftest.py so no real
HTTP port is needed, but real backing services (Postgres, Qdrant, …)
must be available — the CI workflow provides them as service containers.
"""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_health(client: AsyncClient):
    """Health endpoint must return 200 and status=ok without auth."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_login_invalid_credentials(client: AsyncClient):
    """Wrong password must return 401."""
    resp = await client.post(
        "/auth/login",
        data={"username": "nonexistent@example.com", "password": "wrongpassword"},
    )
    assert resp.status_code == 401


async def test_login_success(client: AsyncClient):
    """Admin login must succeed and return an access token."""
    from backend.config import get_settings  # type: ignore[import]

    settings = get_settings()
    resp = await client.post(
        "/auth/login",
        data={
            "username": settings.admin_email,
            "password": settings.admin_password,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


async def test_me_requires_auth(client: AsyncClient):
    """/auth/me must reject unauthenticated requests."""
    resp = await client.get("/auth/me")
    assert resp.status_code == 401


async def test_me_authenticated(client: AsyncClient, auth_headers: dict):
    """/auth/me must return the current user's profile."""
    resp = await client.get("/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "email" in data
    assert "role" in data


async def test_sources_list_requires_auth(client: AsyncClient):
    """/sources/ must reject unauthenticated requests."""
    resp = await client.get("/sources/")
    assert resp.status_code == 401


async def test_sources_list_authenticated(client: AsyncClient, auth_headers: dict):
    """/sources/ must return a list for authenticated users."""
    resp = await client.get("/sources/", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_query_requires_auth(client: AsyncClient):
    """/query/ must reject unauthenticated requests."""
    resp = await client.post("/query/", json={"question": "test", "mode": "rag", "top_k": 3, "strict_grounding": True})
    assert resp.status_code == 401
