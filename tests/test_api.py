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


# ── Chunker unit tests (no backing services needed) ───────────

def test_prose_chunker_html_article():
    """split_prose should return at least one chunk with non-empty text and section_path."""
    from backend.services.chunking import split_prose  # type: ignore[import]

    html = """
    <html><body>
      <h1>Introduction</h1>
      <p>This is the first paragraph of the article. It contains some meaningful content.</p>
      <h2>Background</h2>
      <p>Here is some background information about the topic being discussed at length.</p>
      <p>And another paragraph with more details about the subject matter covered here.</p>
    </body></html>
    """
    chunks = split_prose(html, source_method="html")
    assert len(chunks) >= 1
    assert all(c.text for c in chunks), "All chunks must have non-empty text"
    # At least one chunk should have a section_path derived from the headings
    assert any(c.section_path for c in chunks), "At least one chunk must have section_path set"


def test_table_chunker_html_table():
    """split_tables should return at least one chunk tagged as ChunkType.table."""
    from backend.services.chunking import split_tables  # type: ignore[import]
    from backend.models import ChunkType  # type: ignore[import]

    html = """
    <html><body>
      <table>
        <tr><th>Country</th><th>Population</th></tr>
        <tr><td>France</td><td>68 million</td></tr>
        <tr><td>Germany</td><td>84 million</td></tr>
      </table>
    </body></html>
    """
    chunks = split_tables(html, source_method="html")
    assert len(chunks) >= 1
    assert all(c.chunk_type == ChunkType.table for c in chunks)


def test_vlm_chunker_block_text():
    """split_vlm should return multiple chunks with ChunkType.block when given --- separators."""
    from backend.services.chunking import split_vlm  # type: ignore[import]
    from backend.models import ChunkType  # type: ignore[import]

    text = (
        "# Title\n\nThis is the first block of text from a VLM extraction.\n\n"
        "---\n\n"
        "This is the second block with completely different content.\n\n"
        "---\n\n"
        "And here is a third block to confirm multiple splits work correctly."
    )
    chunks = split_vlm(text)
    assert len(chunks) >= 2, "Should produce multiple chunks from --- separated blocks"
    assert all(c.chunk_type == ChunkType.block for c in chunks)
