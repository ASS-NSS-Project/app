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

## What is Tested

### `test_api.py`

**Health & Metrics:**
- `GET /health` returns `{"status": "ok"}`
- `GET /metrics` returns Prometheus text format

**Authentication:**
- `POST /auth/login` — OAuth2 form login
- `GET /auth/me` — returns authenticated user profile
- `GET /auth/stats` — returns system-wide counts
- `GET /auth/providers` — returns SSO provider config

**Sources:**
- `GET /sources/` — list all sources
- `POST /sources/` — create a new source
- SSRF protection — rejects private/loopback URLs (127.0.0.1, 10.0.0.0/8, 192.168.0.0/16, localhost)

**Query:**
- `POST /query/` — requires authentication (401 without token)

**Documents:**
- `GET /documents/` — list documents (paginated)

**Incidents:**
- `GET /incidents/` — list incidents
- `POST /incidents/simulate` — create synthetic CAPTCHA incident (admin only)

**Chunker unit tests:**
- `split_prose()` — token-measured prose chunking
- `split_tables()` — table extraction and chunking
- `split_vlm()` — VLM block chunking (blank-line separated)

### `test_config.py`

- Settings loading from environment variables
- Required fields validation

---

## Pending Tests (TODO)

- **Experiment endpoints** — waiting for the feature to be fully implemented
- **Ingest pipeline end-to-end** — requires RabbitMQ and Qdrant; currently out of scope for unit tests
- **RAG query with real embeddings** — skipped because BGE-M3 is not loaded in CI (slow, memory-intensive)

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
def test_my_endpoint(client: AsyncClient, auth_headers: dict):
    response = await client.get("/my-endpoint", headers=auth_headers)
    assert response.status_code == 200
```

**Pattern for unauthenticated endpoint tests:**

```python
def test_health(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "rag-api"}
```

---

## Test Coverage

The test suite intentionally focuses on **integration tests** (API endpoints) rather than unit tests (individual functions). This approach:

- Catches regressions in the actual HTTP API contract
- Tests the full stack (router → service → database)
- Reduces test brittleness (implementation details can change without breaking tests)

**Coverage areas:**
- ✓ Authentication (login, token validation, role enforcement)
- ✓ CRUD operations (sources, documents, incidents)
- ✓ Security (SSRF protection, auth gates)
- ✓ Health checks and metrics
- ✓ Chunker algorithms
- ✗ Full ingest pipeline (requires RabbitMQ + Qdrant)
- ✗ RAG query with real embeddings (requires BGE-M3)
- ✗ Experiment batch queries (feature not fully implemented)

---

## Troubleshooting

**Test failures on CI but passes locally:**
- Check environment variables — CI uses different values
- Check Postgres version — CI uses Postgres 16, local might differ
- Check Python version — CI uses 3.11

**`create_schema` fixture fails:**
- Ensure Postgres is running and accessible
- Check connection parameters in environment variables

**`auth_headers` fixture fails:**
- Ensure `FIRST_ADMIN_EMAIL` and `FIRST_ADMIN_PASSWORD` are set
- Check that `create_admin` fixture runs before `auth_headers`

**Import errors:**
- Run `poetry install` to ensure all dependencies are installed
- Check that `PYTHONPATH` includes the backend directory
