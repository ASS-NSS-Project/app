import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


# ── Health & metrics ──────────────────────────────────────────

async def test_health(client: AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "rag-api"


async def test_metrics_available(client: AsyncClient):
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert b"python_gc" in resp.content or b"process_" in resp.content


# ── Auth ──────────────────────────────────────────────────────

async def test_login_invalid_credentials(client: AsyncClient):
    resp = await client.post(
        "/auth/login",
        data={"username": "nonexistent@example.com", "password": "wrongpassword"},
    )
    assert resp.status_code == 401


async def test_login_success(client: AsyncClient):
    from config import get_settings

    s = get_settings()
    resp = await client.post(
        "/auth/login",
        data={"username": s.first_admin_username, "password": s.first_admin_password},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert "role" in data
    assert "user_id" in data


async def test_me_requires_auth(client: AsyncClient):
    resp = await client.get("/auth/me")
    assert resp.status_code == 401


async def test_me_authenticated(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    me = resp.json()
    assert "email" in me
    assert "role" in me
    assert "id" in me
    assert me["role"] == "rag_admin"


async def test_stats_requires_auth(client: AsyncClient):
    resp = await client.get("/auth/stats")
    assert resp.status_code == 401


async def test_stats_authenticated(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/auth/stats", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    for key in ("sources", "jobs", "incidents", "documents"):
        assert key in data
        assert isinstance(data[key], int)


# ── Sources ───────────────────────────────────────────────────

async def test_sources_requires_auth(client: AsyncClient):
    resp = await client.get("/sources/")
    assert resp.status_code == 401


async def test_sources_list_authenticated(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/sources/", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_source_ssrf_protection(client: AsyncClient, auth_headers: dict):
    resp = await client.post(
        "/sources/",
        json={
            "name": "SSRF test",
            "base_url": "http://169.254.169.254/latest/meta-data/",
            "permission_type": "public",
            "preferred_strategy": "html",
        },
        headers=auth_headers,
    )
    assert resp.status_code in (400, 422)


# ── Query ─────────────────────────────────────────────────────

async def test_query_requires_auth(client: AsyncClient):
    resp = await client.post(
        "/query/",
        json={"question": "test", "mode": "rag", "top_k": 3, "strict_grounding": True},
    )
    assert resp.status_code == 401


# ── Documents ─────────────────────────────────────────────────

async def test_documents_requires_auth(client: AsyncClient):
    resp = await client.get("/documents/")
    assert resp.status_code == 401


async def test_documents_list_authenticated(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/documents/", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ── Experiments ───────────────────────────────────────────────

# TODO: add experiment tests once the feature is implemented


# ── Incidents ─────────────────────────────────────────────────

async def test_incidents_requires_auth(client: AsyncClient):
    resp = await client.get("/incidents/")
    assert resp.status_code == 401


async def test_incidents_list_authenticated(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/incidents/", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ── Chunker unit tests (no backing services) ──────────────────

def test_prose_chunker_html_article():
    from services.chunking import split_prose

    html = """
    <html><body>
      <h1>Introduction</h1>
      <p>Retrieval-Augmented Generation combines a retrieval step with a generative language
      model to produce answers that are grounded in a specific document corpus rather than
      relying solely on the model's parametric knowledge acquired during pre-training.</p>
      <h2>Background</h2>
      <p>Dense retrieval systems encode both queries and passages into a shared embedding space
      so that semantically similar texts map to nearby vectors, enabling efficient nearest-neighbour
      search over large document collections using libraries such as Faiss or Qdrant.</p>
      <p>Hybrid retrieval combines dense vector search with sparse keyword matching such as BM25,
      then fuses the ranked lists using Reciprocal Rank Fusion to improve precision across diverse
      query types that benefit from different retrieval signals.</p>
    </body></html>
    """
    chunks = split_prose(html, source_method="html")
    assert len(chunks) >= 1
    assert all(c.text for c in chunks)
    assert any(c.section_path for c in chunks)


def test_table_chunker_html_table():
    from services.chunking import split_tables
    from models import ChunkType

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
    from services.chunking import split_vlm
    from models import ChunkType

    text = (
        "# Title\n\nThis is the first block of text from a VLM extraction.\n\n"
        "---\n\n"
        "This is the second block with completely different content.\n\n"
        "---\n\n"
        "And here is a third block to confirm multiple splits work correctly."
    )
    chunks = split_vlm(text)
    assert len(chunks) >= 2
    assert all(c.chunk_type == ChunkType.block for c in chunks)
