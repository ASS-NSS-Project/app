# RAG System — Multimodal Platform

A production system for scraping web content, extracting structured data with AI vision, and answering questions via RAG (Retrieval-Augmented Generation).

LLM and VLM inference runs on **CERIT-SC AIaaS** (e-INFRA). Object storage uses **CESNET S3**. Everything else — Postgres, RabbitMQ, Qdrant, the API, the worker — runs in Docker/Podman.

---

## What This System Does

1. **Ingests** websites using a multi-strategy pipeline:
   - HTML fetch → Rendered DOM (Playwright) → Screenshot + vision AI
2. **Extracts** structured content from screenshots using a VLM on AIaaS
3. **Indexes** content in Qdrant using BGE-M3 hybrid embeddings (dense + sparse, RRF fusion)
4. **Answers** questions using RAG — retrieves relevant passages, then answers with citations via a text LLM on AIaaS
5. **Tracks** CAPTCHA incidents, audit logs, and evidence files in CESNET S3
6. **Experiments** — run named batch query sets to benchmark retrieval quality over time

---

## Prerequisites

- **Docker** with Compose v2, or **Podman** with podman-compose
- **Git**
- Credentials for **CESNET S3** (object storage) and **CERIT-SC AIaaS** (LLM/VLM endpoints)

---

## Setup

### 1. Clone the repository

```bash
git clone <repository-url> rag_system
cd rag_system
```

### 2. Create your `.env` file

```bash
cp .env.example .env
```

Fill in the required values. The mandatory ones:

```env
# PostgreSQL
POSTGRES_PASSWORD=strong-random-password

# RabbitMQ
RABBITMQ_DEFAULT_PASS=strong-random-password

# CESNET S3
S3_ENDPOINT_URL=https://<provided-by-team>
S3_ACCESS_KEY=<provided-by-team>
S3_SECRET_KEY=<provided-by-team>

# CERIT-SC AIaaS — text LLM
LLM_BASE_URL=https://<aiaas-endpoint>/v1
LLM_API_KEY=<provided-by-team>
LLM_MODEL=<from /v1/models, e.g. llama-3.3-70b-instruct>

# CERIT-SC AIaaS — vision LLM
VLM_BASE_URL=https://<aiaas-endpoint>/v1
VLM_API_KEY=<provided-by-team>
VLM_MODEL=<from /v1/models, e.g. qwen2.5-vl-7b-instruct>

# JWT signing secret
# Generate: python -c "import secrets; print(secrets.token_hex(32))"
JWT_SECRET=your-random-hex-string

# First admin account (created automatically on first startup)
FIRST_ADMIN_EMAIL=admin@example.com
FIRST_ADMIN_PASSWORD=strong-random-password
```

#### Optional: Google OAuth2

To enable "Sign in with Google":

```env
GOOGLE_CLIENT_ID=...your-client-id...
GOOGLE_CLIENT_SECRET=...your-client-secret...
# Production:
GOOGLE_REDIRECT_URI=https://your-domain/auth/google/callback
FRONTEND_URL=https://your-domain
# Local dev:
# GOOGLE_REDIRECT_URI=http://localhost/auth/google/callback
# FRONTEND_URL=http://localhost
```

Create OAuth credentials at [Google Cloud Console](https://console.cloud.google.com/) → APIs & Services → Credentials. Add the redirect URI to **Authorized redirect URIs**. If `GOOGLE_CLIENT_ID` is not set the button returns a `503` and the flow is skipped.

#### Production routing (Traefik + TLS)

```env
DOMAIN=your-server-ip-or-domain
ACME_EMAIL=you@example.com
```

### 3. Create the Traefik certificate file

```bash
touch acme.json && chmod 600 acme.json
```

This **must be a file**, not a directory. If Podman created a directory here from a previous run, delete it first: `rm -rf acme.json && touch acme.json && chmod 600 acme.json`.

### 4. Start the system

**Docker:**
```bash
docker compose up --build
```

**Podman** (rootless — exposes port 80 without TLS):

Rootless Podman cannot bind port 80 by default. Allow it once (requires root):
```bash
echo 'net.ipv4.ip_unprivileged_port_start=80' | sudo tee -a /etc/sysctl.d/99-podman-ports.conf
sudo sysctl -p /etc/sysctl.d/99-podman-ports.conf
```

Enable the Podman user socket (once — survives reboots):
```bash
systemctl --user enable --now podman.socket
```

Add `DOCKER_SOCK` to your `.env` (replace `1000` with your UID from `id -u`):
```
DOCKER_SOCK=/run/user/1000/podman/podman.sock
```

Then start the stack:
```bash
podman compose up --build
```

> **First-time cleanup**: if you have leftover containers from a previous run, do
> `podman compose down -v` first.

The `docker-compose.override.yml` is picked up automatically. It:
- Reconfigures Traefik to run HTTP-only on port 80 (no TLS, no redirect)
- Adds a TCP wait loop before the API and worker start, ensuring Postgres is fully ready
- Wraps the RabbitMQ entrypoint to pre-write the erlang cookie with correct ownership (Podman rootless UID mapping fix)
- Disables SELinux confinement for Traefik and RabbitMQ via `security_opt: label=disable`

You'll know it's ready when you see:
```
rag_api    | INFO: Startup complete. API ready.
rag_worker | INFO: Worker ready. Listening on queue: ingest
```

### 5. Open the UI

Open **http://localhost** and log in with `FIRST_ADMIN_EMAIL` / `FIRST_ADMIN_PASSWORD` from your `.env`.

Docker serves on port 80 with automatic TLS. Podman local dev also serves on port 80, HTTP only (no redirect, no ACME).

---

## API Reference

All endpoints (except `GET /health`) require a JWT token in the `Authorization` header:

```
Authorization: Bearer <token>
```

Obtain a token via `POST /auth/login`. Roles control access: **admin** > **curator** > **analyst** > **user**.

Enable Swagger UI by setting `API_DOCS=true` in `.env`, then visit `/docs`.

---

### Authentication — `/auth`

#### `POST /auth/login`
Authenticate with username/email and password. Returns a JWT token.

**Request** (`application/x-www-form-urlencoded`):
| Field | Type | Description |
|-------|------|-------------|
| `username` | string | Email or username |
| `password` | string | Password |

**Response `200`**:
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "user_id": "uuid",
  "role": "admin",
  "email": "admin@example.com",
  "username": "admin"
}
```

---

#### `GET /auth/google`
Redirects to Google's OAuth2 consent page. No body required.

#### `GET /auth/google/callback`
OAuth2 callback — handled automatically by Google after user consent. Redirects to the frontend with the JWT token as a query parameter.

---

#### `POST /auth/register` *(admin only)*
Create a new user account.

**Request** (`application/json`):
```json
{
  "username": "jsmith",
  "email": "j@example.com",
  "password": "min-12-chars",
  "full_name": "Jane Smith",
  "role": "user"
}
```
`role` is one of: `admin`, `curator`, `analyst`, `user`.

**Response `200`**: `UserResponse` (see below).

---

#### `GET /auth/me`
Returns the currently authenticated user's profile.

**Response `200`**:
```json
{
  "id": "uuid",
  "username": "admin",
  "email": "admin@example.com",
  "full_name": "Admin",
  "role": "admin",
  "is_active": true
}
```

---

#### `GET /auth/stats`
Returns system-wide counts for the dashboard.

**Response `200`**:
```json
{
  "sources": 12,
  "jobs": 480,
  "incidents": 3,
  "documents": 950
}
```

---

#### `GET /auth/audit` *(admin, curator)*
Returns audit log entries, newest first.

**Query params**:
| Param | Default | Description |
|-------|---------|-------------|
| `limit` | `50` | Max entries (1–200) |
| `offset` | `0` | Pagination offset |

**Response `200`**: array of:
```json
{
  "id": "uuid",
  "action": "SOURCE_CREATED",
  "object_type": "source",
  "object_id": "uuid",
  "extra": {"name": "Tech Blog", "url": "https://..."},
  "created_at": "2026-04-19T10:00:00",
  "user_email": "admin@example.com"
}
```

---

#### `GET /auth/users` *(admin, curator)*
Lists all users.

**Response `200`**: array of `UserResponse`.

---

#### `PATCH /auth/users/{user_id}` *(admin only)*
Update a user's role or active status.

**Request** (`application/json`, all fields optional):
```json
{
  "role": "curator",
  "is_active": false
}
```

**Response `200`**: updated `UserResponse`.

---

### Sources — `/sources`

A **source** is a website or URL we want to monitor and ingest.

#### `GET /sources/`
List all active sources.

**Response `200`**: array of:
```json
{
  "id": "uuid",
  "name": "Tech Blog",
  "base_url": "https://techblog.example.com",
  "permission_type": "public",
  "preferred_strategy": "html",
  "crawl_frequency_hours": 24,
  "is_active": true,
  "created_at": "2026-04-19T10:00:00"
}
```

---

#### `POST /sources/` *(admin, curator)*
Create a new source.

**Request** (`application/json`):
```json
{
  "name": "Tech Blog",
  "base_url": "https://techblog.example.com",
  "permission_type": "public",
  "permission_ref": null,
  "preferred_strategy": "html",
  "crawl_frequency_hours": 24,
  "crawl_depth": 1,
  "rate_limit_rps": 1.0,
  "retention_days_evidence": 90
}
```

`preferred_strategy` is one of: `html`, `rendered`, `screenshot`.  
URLs pointing to private/loopback addresses are rejected (SSRF protection).

**Response `200`**: `SourceResponse`.

---

#### `PATCH /sources/{source_id}` *(admin, curator)*
Update a source's settings. All fields are optional.

**Request** (`application/json`):
```json
{
  "name": "New Name",
  "preferred_strategy": "rendered",
  "crawl_frequency_hours": 12,
  "is_active": true
}
```

**Response `200`**: updated `SourceResponse`.

---

#### `DELETE /sources/{source_id}` *(admin only)*
Deactivates a source (soft delete — sets `is_active = false`).

**Response `200`**:
```json
{"message": "Source deactivated"}
```

---

#### `POST /sources/{source_id}/ingest` *(admin, curator)*
Trigger an immediate ingest job for a source.

**Request** (`application/json`, optional):
```json
{
  "url": "https://techblog.example.com/specific-article"
}
```
If `url` is omitted, uses the source's `base_url`.

**Response `200`**:
```json
{
  "id": "uuid",
  "url": "https://techblog.example.com",
  "status": "pending",
  "strategy_used": null,
  "quality_score": null,
  "error_message": null,
  "created_at": "2026-04-19T10:00:00"
}
```

`status` progresses through: `pending` → `running` → `done` | `failed` | `captcha_blocked`.

---

#### `GET /sources/{source_id}/jobs`
List the 50 most recent ingest jobs for a source.

**Response `200`**: array of `JobResponse` (same shape as above, with `strategy_used` and `quality_score` filled in once complete).

---

### Query — `/query`

#### `POST /query/`
Ask a question. Returns an answer with citations from the knowledge base.

**Request** (`application/json`):
```json
{
  "question": "What are the pricing tiers?",
  "mode": "rag",
  "top_k": 5,
  "source_id": null,
  "strict_grounding": true
}
```

| Field | Default | Description |
|-------|---------|-------------|
| `question` | required | The question to answer |
| `mode` | `"rag"` | `"rag"` retrieves chunks first; `"no_rag"` asks the LLM directly |
| `top_k` | `5` | Number of chunks to retrieve |
| `source_id` | `null` | Restrict retrieval to one source (UUID) |
| `strict_grounding` | `true` | If true, LLM only uses retrieved context; if false, may use general knowledge |

**Response `200`**:
```json
{
  "answer": "The system offers three tiers: ...",
  "mode": "rag",
  "citations": [
    {
      "index": 1,
      "url": "https://techblog.example.com/pricing",
      "text": "...relevant excerpt...",
      "relevance_score": 0.912
    }
  ],
  "chunks_retrieved": 5
}
```

---

### Documents — `/documents`

#### `GET /documents/`
List all ingested documents (paginated).

**Query params**: `limit` (default `50`), `offset` (default `0`), `source_id` (optional UUID filter).

**Response `200`**: array of `DocumentResponse`.

---

#### `GET /documents/{doc_id}`
Fetch a single document by ID.

**Response `200`**: `DocumentResponse`.

---

#### `GET /documents/{doc_id}/chunks`
List all chunks for a document.

**Response `200`**: array of `ChunkResponse`.

---

#### `GET /documents/evidence/{evidence_id}/url`
Get a pre-signed download URL for an evidence file (screenshot, HTML dump) stored in CESNET S3.

**Response `200`**:
```json
{"url": "https://s3.example.com/...?X-Amz-Signature=..."}
```

---

### Experiments — `/experiments`

Experiments let you run named batch query sets to benchmark retrieval quality over time.

#### `GET /experiments/`
List all experiments.

#### `POST /experiments/` *(admin, curator)*
Create a new experiment.

**Request** (`application/json`):
```json
{
  "name": "Pricing Q&A benchmark",
  "description": "Tests retrieval accuracy on pricing-related questions",
  "queries": [
    {"question": "What are the pricing tiers?"},
    {"question": "Is there a free plan?"}
  ]
}
```

#### `GET /experiments/{experiment_id}`
Fetch a single experiment with all its query results.

#### `POST /experiments/{experiment_id}/run` *(admin, curator)*
Re-run all queries in the experiment against the current index. Results are updated in place.

#### `DELETE /experiments/{experiment_id}` *(admin only)*
Delete an experiment and all its query results.

---

### Incidents — `/incidents`

Incidents are created automatically when a CAPTCHA or access block is detected during ingestion.

**Testing with a real CAPTCHA page:**
Google's reCAPTCHA demo is a stable developer test page that always contains CAPTCHA markup:
1. Create a source with `base_url: https://www.google.com/recaptcha/api2/demo` and `preferred_strategy: html`
2. Trigger an ingest — the HTML fetcher detects `recaptcha` keywords and creates an incident automatically
3. The incident appears in this list with `detector: html_keyword`

Use `html` strategy (not `rendered` or `screenshot`) — it's the fastest path and sufficient for keyword detection.

#### `GET /incidents/`
List incidents, newest first (max 100).

**Query params**:
| Param | Description |
|-------|-------------|
| `status` | Filter by status: `open`, `in_progress`, `resolved` |

**Response `200`**: array of:
```json
{
  "id": "uuid",
  "type": "captcha",
  "source_id": "uuid",
  "url": "https://example.com/blocked",
  "severity": "medium",
  "status": "open",
  "detector": "html_keyword",
  "evidence_screenshot_uri": "source-id/job-id/captcha_page.png",
  "created_at": "2026-04-19T10:00:00",
  "resolved_at": null,
  "resolution_note": null
}
```

---

#### `POST /incidents/{incident_id}/resolve` *(admin, curator)*
Mark an incident as resolved.

**Request** (`application/json`):
```json
{
  "resolution_note": "Switched to API endpoint, CAPTCHA no longer triggered."
}
```

**Response `200`**: updated incident with `status: "resolved"`, `resolved_at` timestamp, and `resolution_note` filled in.

---

#### `POST /incidents/simulate` *(admin only)*
Create a synthetic CAPTCHA incident for testing. Useful for verifying the UI and resolve workflow without waiting for a real scrape to be blocked.

**Request** (`application/json`, all fields optional):
```json
{
  "source_id": "uuid-of-existing-source",
  "url": "https://example.com/captcha-test",
  "severity": "medium",
  "detector": "simulate"
}
```

If `source_id` is omitted the first active source is used automatically.

**Quick test via curl:**
```bash
TOKEN=$(curl -s -X POST http://127.0.0.1/auth/login \
  -d "username=admin@example.com&password=YOUR_ADMIN_PASSWORD" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -s -X POST http://127.0.0.1/incidents/simulate \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}' | python3 -m json.tool
```

**Response `200`**: the created `IncidentResponse` with `status: "open"`.

---

### Health & Metrics

#### `GET /health`
No authentication required. Returns `200` if the API is running.

```json
{"status": "ok", "service": "rag-api"}
```

#### `GET /metrics`
Prometheus metrics endpoint (no authentication). Scraped by PodMonitor.
The worker also exposes Prometheus metrics on port `9090` (configurable via `WORKER_METRICS_PORT`).

---

## Service URLs

| Service | URL | Notes |
|---------|-----|-------|
| Main UI | http://localhost | Frontend application |
| API | http://localhost (proxied) | FastAPI backend via Traefik |
| Swagger UI | http://localhost/docs | Set `API_DOCS=true` in `.env` to enable |
| ReDoc | http://localhost/redoc | Set `API_DOCS=true` in `.env` to enable |
| Qdrant Dashboard | http://localhost:6333/dashboard | Browse vector collections (localhost only) |
| RabbitMQ Management | http://localhost:15672 | Browse queues (localhost only) |

RabbitMQ login: `RABBITMQ_DEFAULT_USER` / `RABBITMQ_DEFAULT_PASS` from `.env`.

> Admin ports (6333, 15672) are bound to `127.0.0.1` only and not exposed to the network.

---

## Architecture Overview

```
User (Browser)
    │
    ▼
Traefik (ports 80/443 — TLS termination, routing)
    │
    ├──► Frontend / Nginx (Vue 3 SPA)
    │
    └──► FastAPI API
            │── Auth (JWT + Google OAuth2)
            │── Sources API
            │── Query API ──────────────► Qdrant (hybrid vector search)
            │── Documents API               ▲
            │── Experiments API             │ embed BGE-M3 (dense + sparse)
            │── Incidents API               │
            │                               │
            ▼                               │
       RabbitMQ Queue ──────► Worker ──────┘
                                  │
                                  ├── HTML fetch (httpx)
                                  ├── Rendered DOM (Playwright/Chrome)
                                  ├── Screenshot (Playwright)
                                  │       └── VLM (CERIT-SC AIaaS)
                                  │
                                  ├── PostgreSQL (metadata, jobs, audit)
                                  └── CESNET S3 (screenshots, HTML evidence)

LLM/VLM inference: CERIT-SC AIaaS (OpenAI-compatible API)
Embeddings: BGE-M3 via FlagEmbedding (runs locally in the worker)
```

---

## Development

### Enable API docs

Set `API_DOCS=true` in `.env`, then restart the API container:

```bash
docker compose restart api   # or: podman compose restart api
```

- Swagger UI: **http://localhost/docs**
- ReDoc: **http://localhost/redoc**

### Logs

All services emit structured JSON logs. Each line includes `timestamp`, `level`, `logger`, `service`, `message`, and an `event` slug for machine parsing.

```bash
podman compose logs -f api      # API logs
podman compose logs -f worker   # Worker/ingest logs
podman compose logs -f frontend # Nginx logs
```

Filter by event type:
```bash
podman compose logs api | grep '"event": "ingest_completed"'
podman compose logs worker | grep '"event": "embedding_failed"'
```

Event catalogue:

| Event | Service | Meaning |
|-------|---------|---------|
| `ingest_started` | worker | Job picked up from queue |
| `ingest_completed` | worker | Full pipeline succeeded |
| `ingest_failed` | worker | Pipeline raised an exception |
| `ingest_strategy_attempt` | worker | Trying a scraping strategy |
| `ingest_strategy_fallback` | worker | Falling back to next strategy |
| `ingest_strategy_error` | worker | A strategy raised an error |
| `captcha_detected` | worker | CAPTCHA found during ingest |
| `document_created` | worker | Document + chunks saved to DB |
| `embedding_completed` | worker | Chunks upserted into Qdrant |
| `embedding_failed` | worker | Qdrant upsert failed |
| `llm_timeout` | api | LLM request timed out |
| `llm_error` | api | LLM request raised an error |
| `scheduler_job_triggered` | api | Crawl job published to queue |
| `scheduler_crawl_failed` | api | Failed to publish crawl job |
| `scheduler_run_complete` | api | Scheduler tick finished |
| `worker_job_started` | worker | Message dequeued |
| `worker_job_completed` | worker | Job fully processed |
| `worker_job_incomplete` | worker | Job finished with non-done status |
| `worker_job_crashed` | worker | Unexpected exception in job |
| `worker_invalid_message` | worker | Malformed message dropped |

### Restart a single service

```bash
docker compose restart api
```

### Stop everything

```bash
docker compose down          # Stop, keep data volumes
docker compose down -v       # Stop and delete all data (fresh start)
```

---

## Troubleshooting

**API stays on "Waiting for Postgres/RabbitMQ"**
→ Give it 30–60 seconds on first run. Databases take time to initialize. The API and worker use a TCP socket poll loop that waits up to 100 s total before failing.

**Worker not processing jobs**
→ Check `podman compose logs worker`. If it shows import errors, run `podman compose build` again.

**Vision extraction fails**
→ Verify `VLM_BASE_URL`, `VLM_API_KEY`, and `VLM_MODEL` in `.env`. Test the endpoint with `curl -H "Authorization: Bearer $VLM_API_KEY" $VLM_BASE_URL/models`.

**S3 upload errors**
→ Verify `S3_ENDPOINT_URL`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`. Check that the buckets in `S3_BUCKET_EVIDENCE` and `S3_BUCKET_DOCS` exist and the credentials have write access.

**Playwright/screenshot errors**
→ Screenshot strategy needs Chromium in the worker container. If it fails, rebuild: `docker compose build --no-cache worker`.

**Podman: RabbitMQ fails to start (erlang cookie permission denied)**
→ In Podman rootless, the container's UID 0 maps to your host user while the RabbitMQ process runs as UID 999 (a subuid-mapped UID). The entrypoint wrapper in `docker-compose.override.yml` handles this by pre-writing the cookie as UID 999 with mode 400 before the main entrypoint runs. If you see `eacces` or "must be accessible by owner only" errors, ensure the override file is being picked up (`podman compose up` from the project root) and that `rabbitmq_data` volume is clean (`podman compose down -v`).

**Podman: Traefik cannot connect to Docker socket (permission denied)**
→ The socket must be the systemd user socket, not one started with `podman system service` in `/tmp`. Run `systemctl --user enable --now podman.socket` and set `DOCKER_SOCK=/run/user/$(id -u)/podman/podman.sock` in `.env`.

**Podman: cannot bind port 80 (permission denied)**
→ Allow rootless binding of low ports once: `echo 'net.ipv4.ip_unprivileged_port_start=80' | sudo tee -a /etc/sysctl.d/99-podman-ports.conf && sudo sysctl -p /etc/sysctl.d/99-podman-ports.conf`

**acme.json is a directory instead of a file**
→ Podman creates a directory when a volume-mounted file doesn't exist yet. Fix: `rm -rf acme.json && touch acme.json && chmod 600 acme.json`.

---

## Project Structure

```
rag_system/
├── docker-compose.yml          # All services (production config)
├── docker-compose.override.yml # Local dev overrides (HTTP only, Podman fixes)
├── .env.example                # Config template (copy to .env)
├── acme.json                   # Traefik TLS certificate storage (must be a file, not dir)
├── backend/                    # FastAPI Python service
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py                 # App entry point, startup logic, Alembic migrations
│   ├── config.py               # Settings from environment variables
│   ├── database.py             # SQLAlchemy DB connection
│   ├── models.py               # All database tables (ORM)
│   ├── worker.py               # Background job processor (RabbitMQ consumer)
│   ├── alembic.ini             # Database migration config
│   ├── alembic/                # Migration scripts (0001–0005)
│   ├── routers/
│   │   ├── auth.py             # Login, register, JWT tokens, audit log, user management
│   │   ├── auth_google.py      # Google OAuth2 (HMAC-signed stateless state tokens)
│   │   ├── sources.py          # Source management + ingest trigger (SSRF-protected)
│   │   ├── query.py            # RAG query endpoint
│   │   ├── documents.py        # Document/chunk browsing + evidence URL generation
│   │   ├── experiments.py      # Batch query benchmarks
│   │   └── incidents.py        # CAPTCHA incident management
│   └── services/
│       ├── ingest_service.py     # Core scraping pipeline (3 strategies + fallback)
│       ├── chunking.py           # Structure-aware chunking (prose / table / VLM)
│       ├── extraction_service.py # VLM extraction via AIaaS
│       ├── embedding_service.py  # BGE-M3 FlagEmbedding + Qdrant hybrid search
│       ├── rag_service.py        # RAG query engine (LLM via AIaaS)
│       ├── storage_service.py    # CESNET S3 file storage
│       ├── captcha_service.py    # CAPTCHA detection + incident creation
│       ├── auth_service.py       # JWT + bcrypt password hashing
│       ├── scheduler_service.py  # APScheduler: periodic crawls + evidence/index cleanup
│       ├── logging_config.py     # Structured JSON logging (python-json-logger)
│       └── queue_service.py      # RabbitMQ job publisher
└── frontend/                   # Vue 3 + TypeScript SPA
    ├── Dockerfile
    ├── nginx.conf              # Nginx static file server with security headers
    ├── src/
    │   ├── main.ts             # App entry point + OAuth token handler
    │   ├── App.vue             # Root component (auth expiry listener)
    │   ├── router/             # Vue Router (hash-based routing)
    │   ├── stores/             # Pinia state management (auth, query history)
    │   ├── api/                # Axios API client + TypeScript types
    │   ├── views/              # Page components (Dashboard, Sources, Query,
    │   │                       #   Incidents, Audit, Users, Login, Documents,
    │   │                       #   Experiments)
    │   └── components/         # Reusable UI components
    └── package.json
```

---

## CI / CD

Images are built and pushed to **GitHub Container Registry** on every push to `main` or `dev`, and on semver git tags (`v*.*.*`).

| Trigger | Tags produced |
|---------|--------------|
| push to `main` or `dev` | `main-<short-sha>`, `dev-<short-sha>` |
| git tag `v1.2.3` | `1.2.3`, `1.2` |

Images:
- `ghcr.io/ass-nss-project/rag-api` — FastAPI backend (also used for the worker, different `command` in k8s)
- `ghcr.io/ass-nss-project/rag-frontend` — Vue 3 / Nginx SPA

The workflow: commit-message lint → backend tests → frontend build → build & push (main/dev/tags only).

---

## Kubernetes (Production)

The production deployment lives in [ASS-NSS-Project/site-infra](https://github.com/ASS-NSS-Project/site-infra) (branch `kost`), managed by ArgoCD.

| Service | Production URL |
|---------|---------------|
| Main UI + API | https://rag.nss.jkzl.eu |
| RabbitMQ Management | https://rabbitmq-mgmt.nss.jkzl.eu |

ArgoCD sync waves:
- Wave 19 — `rabbitmq-operator` (RabbitMQ Cluster Operator)
- Wave 20 — `qdrant` (Qdrant via Helm)
- Wave 21 — `rag-system` (API, worker, frontend, CNPG Postgres, secrets via ESO/Vault)

Secrets are provisioned via `terraform/vault` in site-infra. DNS records are managed via `terraform/cloudflare`.

---

## TODO

- [ ] **Frontend end-to-end smoke test** — walk the golden path (login → add source → trigger ingest → wait for completion → run a RAG query) to verify all compose fixes and service wiring hold together
- [ ] **Migration 0006: drop `rq_job_id`** — `ingest_jobs.rq_job_id` is a dead column left over from an earlier Redis Queue prototype; nothing writes to it; drop it with a clean Alembic migration
- [ ] **Keycloak OIDC** — replace custom JWT auth with Keycloak OIDC for SSO across all cluster services
