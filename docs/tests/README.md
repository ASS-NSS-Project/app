# Tests Documentation

Pytest-based test suite for the RAG system backend. Tests run against a real PostgreSQL database (no mocking). The suite is intentionally minimal — it covers the critical paths and acts as a regression gate.

---

## Directory Structure

```text
tests/
├── conftest.py      # Pytest fixtures: real Postgres DB, httpx.AsyncClient (ASGI), create_schema, create_admin, auth_headers
├── test_api.py      # Endpoint integration tests (auth, sources, query, incidents, documents) + chunker unit tests
└── test_config.py   # Settings loading tests
```

---

## Test Fixtures (`conftest.py`)

| Fixture | Scope | Purpose |
|---------|-------|---------|
| `create_schema` | session | Creates all DB tables once per session via `Base.metadata.create_all` |
| `create_admin` | session | Calls `ensure_admin_exists` so login tests have a real user |
| `client` | function | async `httpx.AsyncClient` backed by ASGI transport (no real HTTP server needed) |
| `auth_headers` | function | Logs in as the default admin and returns the `Authorization` header dict |

---

## What Is Tested

### `test_api.py`

**Health & Metrics:**
- `GET /health` — returns `{"status": "ok", "service": "rag-api"}`
- `GET /metrics` — returns Prometheus text format

**Authentication:**
- `POST /auth/login` — rejects invalid credentials (401), accepts valid admin credentials (200)
- `GET /auth/me` — requires auth (401 without token), returns user profile with role
- `GET /auth/stats` — requires auth (401 without token), returns integer counts for sources/jobs/incidents/documents

**Sources:**
- `GET /sources/` — requires auth (401), returns list when authenticated
- `POST /sources/` — SSRF protection rejects private/loopback URLs (400 or 422)

**Query:**
- `POST /query/` — requires auth (401 without token) — *only the auth guard is tested, not a successful query*

**Documents:**
- `GET /documents/` — requires auth (401), returns list when authenticated
- `DELETE /documents/{id}` — requires auth (401 without token)

**Incidents:**
- `GET /incidents/` — requires auth (401), returns list when authenticated

**Experiments:**
- `GET /experiments/` — asserts 404 (router registered, no handlers implemented)
- `POST /experiments/` — asserts 404 (same reason)

**Chunker unit tests (no backing services):**
- `split_prose()` — token-measured prose chunking from HTML
- `split_tables()` — table extraction and chunking from HTML
- `split_vlm()` — VLM block chunking (blank-line / `---` separated)

### `test_config.py`

- PostgreSQL URL composition from `POSTGRES_*` fields
- S3/CESNET settings mapping (endpoint, credentials, region, path-style, buckets)
- AIaaS model settings (shared base URL/key, LLM/VLM model names)
- Chunking default values (prose/table/VLM token targets)
- Auth settings defaults and overrides (JWT, admin bootstrap fields)

---

## Known Failures & Gaps

### `test_health` — stale service name
**Status: passes in CI, but assertion is wrong**

`main.py` returns `"service": "rag-api"` and the test asserts `"rag-api"`. The project was renamed to `webrag` but neither the health endpoint nor the test was updated. Both need to change to `"webrag-api"` together — doing one without the other would break CI.

---

### Experiments router — not implemented
**Status: tests pass by asserting 404, comment in router is wrong**

`routers/experiments.py` is registered but has **no route handlers** — only TODO comments. FastAPI returns `404 Not Found` for all `/experiments/*` requests because the routes simply do not exist. The tests assert `404` and pass, but:
- The router file states `"returns 501"` — incorrect, it returns 404
- The tests are checking absence of a route, not a deliberate "not implemented" response
- `services/experiment_service.py` and the DB schema (`experiments`, `experiment_queries` tables via migration `0005_experiments.py`) exist — the service layer is ready, only the router handlers are missing

---

### API token endpoints — zero coverage
**Status: not tested at all**

`GET /auth/api-token/status` and `POST /auth/api-token` were added to support opaque long-lived tokens (90-day default, SHA-256 hashed). No tests exist for:
- Generating a token
- Verifying the token works as `Authorization: Bearer <opaque>` on protected endpoints
- The `401 "API token expired"` response when a token has passed its expiry
- Regeneration (second `POST` replaces the previous token)

---

### Authenticated query — auth guard only
**Status: intentionally skipped**

`test_query_requires_auth` only checks that unauthenticated requests are rejected. A successful `POST /query/` requires:
- Qdrant running and a collection populated with embeddings
- BGE-M3 model loaded (~2.3 GB, slow first-boot download)
- An OpenAI-compatible LLM endpoint reachable

These are not available in CI. There is no mock or fixture path to test the RAG retrieval and answer generation logic.

---

### Ingest pipeline — not tested
**Status: intentionally skipped**

`POST /sources/{id}/ingest` publishes a job to RabbitMQ; the worker picks it up and runs the 4-strategy scrape pipeline. Testing this end-to-end requires:
- RabbitMQ running and reachable
- Playwright Chromium installed (for `rendered` and `screenshot` strategies)
- S3-compatible storage for evidence upload
- BGE-M3 for embedding

None of these are present in CI. The worker (`worker_ingest.py`, `worker_embed.py`) has no unit tests.

---

### OAuth / OIDC routes — not tested
**Status: intentionally skipped**

`GET /auth/keycloak` and `GET /auth/keycloak/callback` require a live Keycloak instance and a browser redirect flow that cannot be replicated with ASGI transport. The `GET /auth/providers` endpoint (returns `{"keycloak": true/false}`) is listed in older docs as tested — it is **not** in the current `test_api.py`.

---

### `POST /incidents/simulate` — listed in old docs, not in test suite
**Status: missing test**

The incident simulation endpoint (creates a synthetic CAPTCHA incident, admin-only) is documented as tested but is absent from `test_api.py`. It should be straightforward to add.

---

## Running Tests Locally

### Prerequisites

Set the required environment variables (same as local dev — copy `.env.example` to `.env`):

```bash
export POSTGRES_USER=rag
export POSTGRES_PASSWORD=rag
export POSTGRES_DB=rag
export POSTGRES_HOST=localhost
export JWT_SECRET=local-test-secret
export FIRST_ADMIN_EMAIL=admin@test.local
export FIRST_ADMIN_PASSWORD=testpassword123
export FRONTEND_URL=http://localhost:5173
```

### Install dependencies

```bash
cd backend
poetry install          # includes dev group (pytest, pytest-asyncio)
```

### Run tests

```bash
cd backend
poetry run pytest ../tests/ -v
```

---

## CI Status

`backend-tests` runs in GitHub Actions against PostgreSQL 16 on every PR/push to `main` or `kost`. The image build job is gated on both backend tests and frontend build, so **failed tests block image publishing immediately**.

**CI workflow file:** `.github/workflows/ci.yml`

**CI test job steps:**
1. Checkout code
2. Start PostgreSQL 16 service
3. Set up Python 3.11
4. Install Poetry
5. Install dependencies (`poetry install`)
6. Run pytest (`poetry run pytest tests/ -v`)

If any test fails, the workflow stops and the Docker images are not built.

---

## Test Database

Tests use a **real PostgreSQL database** (not SQLite in-memory, not mocks). This ensures that:

- SQLAlchemy models match the actual database schema
- Queries work as expected against real Postgres (type casting, JSON fields, etc.)
- Foreign key constraints are enforced

The database is created fresh for each test session via the `create_schema` fixture.

---

## Adding New Tests

1. **Endpoint tests** — add to `test_api.py` under the appropriate section
2. **Service/utility tests** — add to `test_api.py` or create a new `test_<module>.py` file
3. **Config tests** — add to `test_config.py`

**Pattern for authenticated endpoint tests:**

```python
async def test_my_endpoint(client: AsyncClient, auth_headers: dict):
    response = await client.get("/my-endpoint", headers=auth_headers)
    assert response.status_code == 200
```

**Pattern for unauthenticated endpoint tests:**

```python
async def test_my_endpoint_requires_auth(client: AsyncClient):
    response = await client.get("/my-endpoint")
    assert response.status_code == 401
```

---

## Coverage Summary

| Area | Covered | Notes |
|------|---------|-------|
| Auth (login, token validation, role enforcement) | ✓ | API token endpoints not covered |
| CRUD (sources, documents, incidents) | ✓ | Auth guards + list operations only |
| SSRF protection | ✓ | |
| Health check and metrics | ✓ | Service name assertion is stale (`rag-api` → should be `webrag-api`) |
| Chunker algorithms | ✓ | Prose, table, VLM block |
| Settings loading | ✓ | |
| API token generate/verify/expire | ✗ | No tests written yet |
| Experiments router | ✗ | Router not implemented — tests assert 404 |
| Full ingest pipeline | ✗ | Requires RabbitMQ, Playwright, S3, BGE-M3 |
| RAG query with embeddings | ✗ | Requires Qdrant + BGE-M3 + LLM |
| OAuth / OIDC flows | ✗ | Requires live Keycloak / Google |
| Incident simulation | ✗ | Endpoint exists, test missing |
