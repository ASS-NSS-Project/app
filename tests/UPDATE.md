# Tests — Changes from ASS-NSS-Project/repo

This document describes how the test suite compares to the reference repo.

---

## Structure (same as reference repo)

```
tests/
├── conftest.py   — pytest fixtures (async ASGI client, auth headers)
└── test_api.py   — integration tests
```

---

## What was adopted from the reference repo

- Same toolchain: `pytest` + `pytest-asyncio` + `httpx.AsyncClient` with
  `ASGITransport` (in-process, no real HTTP port).
- Same fixture pattern: `client` fixture yields an `AsyncClient` backed by
  the FastAPI app.

---

## What is different

### Tests cover our actual endpoints

The reference repo tests `/rag/add` and `/rag/ask` (simple in-memory RAG).
Our tests cover the real API surface:

| Test | What it checks |
|------|---------------|
| `test_health` | `GET /health` → 200, no auth |
| `test_login_invalid_credentials` | Wrong creds → 401 |
| `test_login_success` | Admin login → token returned |
| `test_me_requires_auth` | `/auth/me` without token → 401 |
| `test_me_authenticated` | `/auth/me` with token → user profile |
| `test_sources_list_requires_auth` | `/sources/` without token → 401 |
| `test_sources_list_authenticated` | `/sources/` with token → list |
| `test_query_requires_auth` | `/query/` without token → 401 |

### `conftest.py` additions

- `auth_headers` fixture: logs in as the configured admin and returns the
  `Authorization` header dict.
- Admin credentials are read from `backend.config.get_settings()` so they
  match whatever `.env` is loaded during the test run.

### Real backing services required

Because the backend runs Alembic migrations and connects to PostgreSQL on
startup, tests require a real database.  In CI this is provided by a
PostgreSQL service container (see `.github/workflows/ci.yml`).

For local runs, start the full stack first:

```bash
docker compose up -d postgres redis
cd backend && pip install -r requirements.txt
pip install pytest pytest-asyncio httpx
pytest tests/ -v
```

---

## Adding new tests

Follow the pattern in `test_api.py`:

```python
async def test_something(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/some/endpoint", headers=auth_headers)
    assert resp.status_code == 200
```
