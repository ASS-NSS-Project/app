# WebRAG — Multimodal RAG Platform

A production system for scraping web content, extracting structured data with AI vision, and answering questions via RAG (Retrieval-Augmented Generation).

LLM and VLM inference runs on **CERIT-SC AIaaS** (e-INFRA). Object storage uses **MinIO** for local dev and **CESNET S3** in production. Everything else — Postgres, RabbitMQ, Qdrant, the API, the worker — runs in Docker/Podman.

---

## What This System Does

1. **Ingests** websites using a multi-strategy pipeline (completes in 30 seconds):
   - API/Feed (Jina.ai reader + RSS fallback) → HTML fetch → Rendered DOM (Playwright) → Screenshot + vision AI
   - All content standardized to markdown and stored in S3 + Postgres
2. **Extracts** structured content from screenshots using a VLM on AIaaS
3. **Indexes** content in Qdrant using BGE-M3 hybrid embeddings (dense + sparse, RRF fusion)
   - Embedding happens **asynchronously in background** (1-5 minutes)
4. **Answers** questions using RAG — retrieves relevant passages, then answers with citations via a text LLM on AIaaS
   - **Keyword fallback** if Qdrant is down (Postgres full-text search)
5. **Tracks** CAPTCHA incidents, audit logs, and evidence files in S3-compatible object storage
6. **Experiments** — run named batch query sets to benchmark retrieval quality over time
7. **Auto-heals** drift between Postgres and Qdrant (background service runs every 15-30 minutes)

---

## Prerequisites

- **Docker** with Compose v2, or **Podman** with podman-compose
- **Git**
- Credentials for **CERIT-SC AIaaS** (LLM/VLM endpoints)

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

Fill in the required values:

```env
# PostgreSQL
POSTGRES_USER=raguser
POSTGRES_PASSWORD=change_me_strong_password
POSTGRES_DB=ragdb

# RabbitMQ
RABBITMQ_DEFAULT_USER=raguser
RABBITMQ_DEFAULT_PASS=change_me_strong_password

# Local dev object storage (MinIO from docker-compose)
S3_ENDPOINT_URL=http://minio:9000
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
S3_USE_PATH_STYLE=true
S3_BUCKET_EVIDENCE=rag-evidence-dev
S3_BUCKET_DOCS=rag-documents-dev

# LLM — text generation (any OpenAI-compatible endpoint)
QUERY_BASE_URL=https://llm.ai.e-infra.cz/v1
QUERY_API_KEY=<your-api-key>
QUERY_MODEL=qwen3.5-122b

# VLM — vision extraction (can use a different endpoint/model)
VLM_BASE_URL=https://llm.ai.e-infra.cz/v1
VLM_API_KEY=<your-api-key>
VLM_MODEL=qwen3.5-122b
# ANTHROPIC_API_KEY=sk-ant-... # enables Claude Opus 4.7, Sonnet 4.6, Haiku 4.5 (direct Anthropic API)

# JWT signing secret
# Generate: python -c "import secrets; print(secrets.token_hex(32))"
JWT_SECRET=change_me_to_a_random_hex_string

# First admin account (created automatically on first startup)
FIRST_ADMIN_USERNAME=admin
FIRST_ADMIN_EMAIL=admin@example.com
FIRST_ADMIN_PASSWORD=change_me_strong_password

# Keycloak OIDC — leave commented out for pure local dev (JWT login still works)
# KEYCLOAK_URL=https://keycloak.nss.jkzl.eu
# KEYCLOAK_REALM=ass-nss-project
# KEYCLOAK_CLIENT_ID=rag-system
# KEYCLOAK_CLIENT_SECRET=<Keycloak admin → Clients → rag-system → Credentials>
# KEYCLOAK_REDIRECT_URI=http://localhost/auth/keycloak/callback
# FRONTEND_URL=http://localhost
```

### 3. Start the system

```bash
docker compose up --build
```

> **First-time cleanup**: if you have leftover containers from a previous run, run `podman compose down -v` first.

You'll know it's ready when you see:
```
rag_api    | INFO: Startup complete. API ready.
rag_worker_ingest | INFO: Worker ready. Listening on queue: ingest
```

### 4. Open the UI

Open **http://localhost:8080** and log in with `FIRST_ADMIN_EMAIL` / `FIRST_ADMIN_PASSWORD` from your `.env`.

---

## API Reference

All endpoints (except `GET /health`) require a JWT token in the `Authorization` header:

```
Authorization: Bearer <token>
```

Obtain a token via `POST /auth/login`. Roles control access: **rag_admin** > **rag_curator** > **rag_analyst** > **rag_user**.

**Frontend navigation visibility by role:**

| Section | rag_admin | rag_curator | rag_analyst | rag_user |
|---------|-----------|-------------|-------------|----------|
| Query (RAG) | ✓ | ✓ | ✓ | ✓ |
| Knowledge Base | ✓ | ✓ | ✓ | — |
| Sources, Pipeline, Incidents | ✓ | ✓ | — | — |
| Experiments | ✓ | — | ✓ | — |
| Dashboard ↗ (Grafana) | ✓ | ✓ | ✓ | — |
| Audit Logs ↗ (Grafana) | ✓ | ✓ | ✓ | — |
| Users ↗ (Keycloak) | ✓ | — | — | — |

The router enforces roles client-side and redirects to `/query` if the role is insufficient. Dashboard, Audit Logs, and Users management all open as external links — there are no in-app pages for these. `/query` is the default landing page for all authenticated roles.

Enable Swagger UI by setting `API_DOCS=true` in `.env`, then visit `/docs`.

---

### Authentication — `/auth`

#### `GET /auth/providers`
Public — returns which SSO providers are configured. Used by the frontend to show/hide the Keycloak login button.

**Response `200`**:
```json
{"keycloak": true}
```

---

#### `POST /auth/login`
OAuth2 form login. For API and script access where form encoding is preferred.

**Request** (`application/x-www-form-urlencoded`):
| Field | Type | Description |
|-------|------|-------------|
| `username` | string | Username |
| `password` | string | Password |

**Response `200`**:
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "user_id": "uuid",
  "role": "rag_admin",
  "email": "admin@example.com",
  "username": "admin"
}
```

---

#### `POST /auth/local-login`
Password-only login for the local admin account. Used by the UI login form.

**Request** (`application/json`):
```json
{"password": "your-admin-password"}
```

**Response `200`**: same shape as `/auth/login`.

---

#### `GET /auth/me`
Returns the currently authenticated user's profile.

**Response `200`**:
```json
{
  "id": "uuid",
  "username": "admin",
  "email": "admin@example.com",
  "full_name": null,
  "role": "rag_admin",
  "is_active": true
}
```

---

#### `POST /auth/refresh`
Re-issues a JWT with the current DB role. Called by the frontend when a role mismatch is detected (e.g. after a Keycloak group change).

**Response `200`**: same shape as `/auth/login`.

---

#### `GET /auth/stats`
Returns system-wide counts and chart data.

**Response `200`**:
```json
{
  "sources": 12,
  "jobs": 480,
  "incidents": 3,
  "documents": 950,
  "strategy_distribution": {
    "api": 42,
    "html": 31,
    "rendered": 16,
    "screenshot": 11
  },
  "activity_24h": [
    {"hour": "08:00", "count": 12},
    {"hour": "09:00", "count": 7}
  ]
}
```

`strategy_distribution` is strategy name → percentage of completed jobs. `activity_24h` has one entry per hour for the last 24 hours.

---

#### `GET /auth/keycloak`
Redirects to the Keycloak OIDC authorization endpoint. Shown as the **"Sign in with OIDC"** button on the login page when `KEYCLOAK_URL` and `KEYCLOAK_CLIENT_ID` are configured.

#### `GET /auth/keycloak/callback`
OIDC callback — handled automatically by Keycloak. Redirects to the frontend with the JWT as a `?token=` query parameter.

User management (create, edit roles, deactivate) is done directly in Keycloak. Keycloak group membership maps to RAG roles: `admin`/`rag_admin` → `rag_admin`, `rag_curator` → `rag_curator`, `rag_analyst` → `rag_analyst`, `rag_user` → `rag_user`.

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
  "preferred_strategy": "api",
  "crawl_frequency_hours": 24,
  "is_active": true,
  "created_at": "2026-04-19T10:00:00",
  "last_crawled_at": "2026-04-20T08:30:00",
  "doc_count": 142
}
```

`last_crawled_at` is `null` until the first successful crawl. `doc_count` is the number of indexed documents for this source.

---

#### `POST /sources/` *(rag_admin, rag_curator)*
Create a new source.

**Request** (`application/json`):
```json
{
  "name": "Tech Blog",
  "base_url": "https://techblog.example.com",
  "permission_type": "public",
  "permission_ref": null,
  "preferred_strategy": "api",
  "crawl_frequency_hours": 24,
  "crawl_depth": 1,
  "rate_limit_rps": 1.0,
  "retention_days_evidence": 90
}
```

`preferred_strategy` is one of: `api` (default — Jina.ai reader + RSS fallback), `html`, `rendered`, `screenshot`.  
The `api` strategy fetches `https://r.jina.ai/{url}`, strips the Jina metadata preamble (Title / URL Source / Markdown Content lines), and chunks the resulting markdown using the VLM block chunker (blank-line separated). The `html` and `rendered` strategies use BeautifulSoup for encoding detection (reads `<meta charset>` from the raw bytes, not the Content-Type header) to correctly handle non-ASCII characters including Czech, Slovak, and other Central/Eastern European scripts.  
URLs pointing to private/loopback addresses are rejected (SSRF protection).

**Response `200`**: `SourceResponse`.

---

#### `PATCH /sources/{source_id}` *(rag_admin, rag_curator)*
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

#### `DELETE /sources/{source_id}` *(rag_admin only)*
Deactivates a source (soft delete — sets `is_active = false`).

**Response `200`**:
```json
{"message": "Source deactivated"}
```

---

#### `POST /sources/{source_id}/ingest` *(rag_admin, rag_curator)*
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
  "created_at": "2026-04-19T10:00:00",
  "started_at": null,
  "finished_at": null
}
```

`status` progresses through: `pending` → `running` → `done` | `failed` | `captcha_blocked`. `started_at` and `finished_at` are populated once the worker picks up and completes the job.

Worker recovery behavior: if a RabbitMQ message is redelivered after a worker restart (for example OOMKill during embedding), the worker does not blindly skip non-`pending` jobs. It resumes `running` jobs and retries the embedding step for `done` jobs to prevent "document/chunks saved but vectors missing" drift.

Qdrant/Postgres drift handling: on API startup, if Postgres has zero chunks but Qdrant still contains vectors (for example after DB reset with persistent Qdrant volume), the collection is recreated automatically. During search, stale vectors whose `chunk_id` no longer exists in Postgres are filtered out and deleted from Qdrant as best-effort cleanup.

---

#### `GET /sources/pipeline/stats`
Returns current pipeline queue statistics for the Pipeline dashboard.

**Response `200`**:
```json
{
  "pending": 3,
  "running": 1,
  "error_rate_24h": 5.2
}
```

`error_rate_24h` is the percentage of jobs created in the last 24 hours that ended in `failed` or `captcha_blocked`.

In the Pipeline UI fallback chain, step badges use `-`, `PENDING`, `READY`, `FAILED`, and `SKIPPED` statuses. If a later strategy is selected directly (for example screenshot extraction), predecessor steps are shown as `SKIPPED` in blue. The chain legend explains each method, including the `jina.ai` reader path and the VLM-based visual extraction step.
The fallback chain renders as four equal-width cards across the available row width, with no numeric step badges. The methods legend is displayed below the chain as a full-width panel to avoid overlap on wide and narrow screens.

---

#### `GET /sources/jobs/all`
List all ingest jobs across all sources. Supports `source_id`, `status`, `limit`, and `offset` query params.

**Response `200`**: array of `JobResponse` extended with `source_name` and `source_base_url`.

---

#### `POST /sources/jobs/{job_id}/cancel` *(rag_admin, rag_curator)*
Cancel a `pending` or `running` job.

---

#### `DELETE /sources/jobs/{job_id}` *(rag_admin only)*
Delete a completed/failed job record.

---

#### `GET /sources/{source_id}/jobs`
List the 50 most recent ingest jobs for a source.

**Response `200`**: array of `JobResponse` (same shape as above, with `strategy_used` and `quality_score` filled in once complete).

---

### Query — `/query`

#### `GET /query/models`
Returns the list of available LLM models. AIaaS models are always present; external provider models are included only when the corresponding API key is configured in the backend environment.

| Provider | Env var | Models exposed |
|----------|---------|----------------|
| AIaaS — e-INFRA | always on | Qwen3.5 122B, DeepSeek V3.2, GPT-OSS 120B |
| OpenAI | `OPENAI_API_KEY` | GPT-4.1, GPT-4.1 Mini, GPT-4.1 Nano, GPT-4o, GPT-4o Mini, o4-mini, o3 |
| Gemini | `GEMINI_API_KEY` | Gemini 2.5 Pro, Gemini 2.5 Flash, Gemini 2.0 Flash, Gemini 3.0 Flash, Gemini 3.1 Pro |
| Anthropic (direct) | `ANTHROPIC_API_KEY` | Claude Opus 4.7, Claude Sonnet 4.6, Claude Haiku 4.5 |

Each entry in the response has `id` (e.g. `"anthropic:claude-opus-4-7"`), `label`, `model` (raw model name), and `group`. The frontend uses this list to populate the model selector — no API keys are ever sent to or stored by the frontend.

#### `POST /query/`
Ask a question. Returns an answer with citations from the knowledge base.

**Request** (`application/json`):
```json
{
  "question": "What are the pricing tiers?",
  "mode": "rag",
  "top_k": 5,
  "source_id": null,
  "strict_grounding": true,
  "upstream_model": "qwen3.5-122b"
}
```

| Field | Default | Description |
|-------|---------|-------------|
| `question` | required | The question to answer |
| `mode` | `"rag"` | `"rag"` retrieves chunks first; `"no_rag"` asks the LLM directly |
| `top_k` | `5` | Number of chunks to retrieve |
| `source_id` | `null` | Restrict retrieval to one source (UUID) |
| `strict_grounding` | `true` | If true, LLM only uses retrieved context; if false, may use general knowledge |
| `upstream_base_url` | `null` | Override the server-configured LLM endpoint (any OpenAI-compatible URL) |
| `upstream_api_key` | `null` | API key for the custom upstream endpoint |
| `upstream_model` | `null` | Model name for the upstream endpoint |

Leave all `upstream_*` fields empty to use the server-configured defaults (`QUERY_BASE_URL` / `QUERY_MODEL`). The `enable_thinking` extra body is only sent when using the default endpoint — suppressed for custom upstreams.

In the Query UI, the autosizing input resets back to compact height when cleared (including whitespace-only content).

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

In the Knowledge Base UI, chunks are opened explicitly via the **Chunks** action button in each row (row click does not open chunks). The document search box filters by document title and URL text, and the Source ID filter is a selectable list populated from known sources. Source IDs are shown in full in the table and the selector.

**Response `200`**: array of `ChunkResponse`.

---

#### `DELETE /documents/{doc_id}` *(rag_admin, rag_curator)*
Delete a document and all of its chunks from the knowledge base. Embedded vectors for that document's chunks are removed from Qdrant as part of the same operation.

**Response `204`**: deleted.

---

#### `GET /documents/{doc_id}/markdown`
Download the full document content as a `.md` file. Documents ingested after the 0006 migration have clean Markdown stored natively (HTML/rendered strategies via `markdownify`, VLM via prompt). Older documents fall back to concatenating their chunks.

**Response `200`**: `text/markdown` with `Content-Disposition: attachment`.

---

#### `GET /documents/evidence/{evidence_id}/url`
Get a pre-signed download URL for an evidence file (screenshot, HTML dump) stored in CESNET S3.

**Response `200`**:
```json
{"url": "https://s3.example.com/...?X-Amz-Signature=..."}
```

---

### Experiments — `/experiments`

Experiments are currently scaffolded in code but not implemented in the running API.  
The router is registered, but no experiment endpoints are exposed yet; requests under `/experiments/` currently return `404`.

---

### Incidents — `/incidents`

Incidents are created automatically when a CAPTCHA or access block is detected during ingestion.

**Testing with a real CAPTCHA page:**
Google's reCAPTCHA demo is a stable developer test page that always contains CAPTCHA markup:
1. Create a source with `base_url: https://www.google.com/recaptcha/api2/demo` and `preferred_strategy: rendered`
2. Trigger an ingest — the rendered strategy runs Playwright, which detects the reCAPTCHA widget and creates an incident automatically
3. The incident appears in this list with `detector: html_keyword`

Use `rendered` strategy — the widget is injected by JavaScript so a plain HTML fetch misses it.

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

#### `POST /incidents/{incident_id}/resolve` *(rag_admin, rag_curator)*
Mark an incident as resolved.

**Request** (`application/json`):
```json
{
  "resolution_note": "Switched to API endpoint, CAPTCHA no longer triggered."
}
```

**Response `200`**: updated incident with `status: "resolved"`, `resolved_at` timestamp, and `resolution_note` filled in.

---

#### `POST /incidents/simulate` *(rag_admin only)*
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
Prometheus metrics endpoint (no authentication). Scraped by the `webrag-api` ServiceMonitor (`infra/argocd/apps/webrag/config/webrag-api-ServiceMonitor.yaml`) every 30 s.

Exported metrics:

| Metric | Type | Labels |
|--------|------|--------|
| `rag_ingest_jobs_total` | Counter | `status`, `strategy` |
| `rag_ingest_duration_seconds` | Histogram | `strategy` |
| `rag_query_requests_total` | Counter | `mode` |
| `rag_query_latency_seconds` | Histogram | `mode` |
| `rag_chunks_embedded_total` | Counter | — |
| `rag_embedding_duration_seconds` | Histogram | — |
| `rag_captcha_incidents_total` | Counter | `strategy` |
| `rag_active_sources` | Gauge | — |
| `rag_open_incidents` | Gauge | — |
| `rag_qdrant_collection_size` | Gauge | — |

The three Gauges (`rag_active_sources`, `rag_open_incidents`, `rag_qdrant_collection_size`) are refreshed every 5 minutes by the APScheduler `gauge_refresh` job in `services/scheduler.py`.

---

## Service URLs

| Service | URL | Notes |
|---------|-----|-------|
| Main UI | http://localhost:8080 | Frontend (nginx proxies API paths) |
| API direct | http://localhost:8000 | FastAPI backend (also reachable directly) |
| Swagger UI | http://localhost:8000/docs | Set `API_DOCS=true` in `.env` to enable |
| ReDoc | http://localhost:8000/redoc | Set `API_DOCS=true` in `.env` to enable |
| Qdrant Dashboard | http://localhost:6333/dashboard | Browse vector collections |
| RabbitMQ Management | http://localhost:15672 | Browse queues |

RabbitMQ login: `RABBITMQ_DEFAULT_USER` / `RABBITMQ_DEFAULT_PASS` from `.env`.

> Qdrant (6333) and RabbitMQ (15672) are bound to `127.0.0.1` only.

---

## Architecture Overview

```
User (Browser)
    │
    ▼
Frontend / Nginx :8080 (host) → :80 (container)
    │  (proxies /auth, /sources, /query, … to API)
    │
    └──► FastAPI API :8000
            │── Auth (JWT + Keycloak OIDC)
            │── Sources API
            │── Query API ──────────────► Qdrant :6333 (hybrid vector search)
            │                              ▲    │  OR (if down)
            │                              │    └──► Postgres full-text (fallback)
            │── Documents API              │
            │── Experiments API            │
            │── Incidents API              │
            │── Scheduler (healing)        │
            │                              │
            ▼                              │
       RabbitMQ :5672                      │
            │                              │
            ├──► Ingest Worker (30s) ─────┤
            │       ├── HTML fetch         │
            │       ├── Playwright         │
            │       ├── VLM extraction     │
            │       ├── Store to S3 (markdown + chunks.json)
            │       └── Store to Postgres  │
            │                              │
            └──► Embedding Worker (1-5min) ┘
                    ├── BGE-M3 embed (dense + sparse)
                    ├── Upsert to Qdrant
                    ├── Optional: backup to S3
                    └── Update chunk status

Storage layers:
├─ PostgreSQL :5432 (metadata, jobs, audit, chunks with status tracking)
├─ MinIO/CESNET S3 (screenshots, markdown, chunks.json, optional embedding backups)
└─ Qdrant :6333 (rebuilable vector index, hot cache)

LLM/VLM inference: CERIT-SC AIaaS (OpenAI-compatible API)
Embeddings: BGE-M3 via FlagEmbedding (runs locally in embedding worker)
Production deployment: Kubernetes — see infra/
```

**Key features:**
- **5-minute SLA:** Keyword search works immediately, vectors ready in 1-5 minutes
- **Resilience:** Qdrant down? Falls back to Postgres full-text automatically
- **Auto-healing:** Background jobs fix drift every 15-30 minutes
- **S3 as truth:** Qdrant is rebuilable from S3/Postgres backups

---

## Object Storage (MinIO + CESNET S3)

The system stores evidence files (screenshots, HTML dumps) and extracted document content in S3-compatible object storage.

### Local development

Local compose includes a MinIO container and auto-creates dev buckets on startup:

| Variable | Dev value |
|----------|-----------|
| `S3_BUCKET_EVIDENCE` | `rag-evidence-dev` |
| `S3_BUCKET_DOCS` | `rag-documents-dev` |
| `S3_USE_PATH_STYLE` | `true` |

If you disable MinIO and point to a different S3 endpoint, those buckets must already exist. The app no longer creates buckets automatically — if a bucket is missing or the credentials are wrong, the API logs a structured error on startup (`event: s3_bucket_missing` or `event: s3_bucket_auth_error`) and refuses to start.

### Production (Kubernetes, CESNET S3)

Prod buckets are provisioned by Terraform (`infra/terraform/du-cesnet`) and locked down with a bucket policy that **denies all anonymous requests**:

| Variable | Prod value |
|----------|-----------|
| `S3_BUCKET_EVIDENCE` | `rag-evidence-prod` |
| `S3_BUCKET_DOCS` | `rag-documents-prod` |
| `S3_USE_PATH_STYLE` | `false` |

Credentials are injected via Vault → ESO → Kubernetes Secret. A random internet user who obtains an object URL gets `403 AccessDenied` — the bucket policy rejects requests without valid HMAC credentials.

### Evidence download URLs

The browser never holds S3 credentials. When the frontend requests an evidence file, the API generates a **presigned URL** — a time-limited URL with a cryptographic signature in the query string. The browser fetches it directly within the expiry window (1 hour) without any credentials. After expiry the URL is useless.

---

## Embedding Model (BGE-M3)

The system uses **BAAI/bge-m3** via [FlagEmbedding](https://github.com/FlagOpen/FlagEmbedding) for both dense and sparse vector generation. The model runs entirely locally — no API key or external service required for embeddings.

| Property | Value |
|----------|-------|
| Model | `BAAI/bge-m3` (fp16) |
| Download size | ~570 MB |
| RAM when loaded | ~2.3 GB |
| Used by | API (query embedding) and worker (chunk embedding) |

### First run — model download

On the very first startup the model is downloaded from Hugging Face Hub (~570 MB). Subsequent starts load it from the `hf_cache` Docker volume, which is shared between the `api` and `worker` containers so the download happens only once.

```
rag_api    | {"event": "model_load_start", ...}
rag_api    | {"event": "model_load_complete", ...}   ← ready after this line
```

`HF_HUB_DISABLE_PROGRESS_BARS=1` is set in all environments so the download does not pollute the structured JSON logs with tqdm progress bars.

### Slow startup

Loading BGE-M3 from disk into memory (~2.3 GB) takes **15–45 seconds** depending on disk speed. This is normal. The API does not accept requests until the model is fully loaded and the readiness probe passes (`GET /health` returns 200).

If startup feels stuck, watch the logs:

```bash
podman compose logs -f api | grep '"event"'
```

You should see `model_load_start` followed by `model_load_complete`, then `startup`.

### Build time

Dependencies are managed with **Poetry** (`pyproject.toml` + `poetry.lock`). `sentence-transformers` and `FlagEmbedding` transitively depend on PyTorch. The `pytorch-cpu` supplemental source in `pyproject.toml` pins torch to the CPU-only wheels (~250 MB) instead of the default CUDA variant (~2 GB). The Dockerfile sets `POETRY_VIRTUALENVS_CREATE=false` so Poetry installs directly into the system Python (appropriate for containers). The BuildKit cache mount (`--mount=type=cache,target=/root/.cache/pypoetry`) keeps downloaded wheels across rebuilds.

**Local dev setup:**
```bash
cd backend
poetry install          # installs all deps including dev (pytest etc.)
poetry shell            # activate the virtualenv
```

After adding or updating dependencies, run `poetry lock` to regenerate `poetry.lock` and commit both files.

---

## Development

### Enable API docs

Set `API_DOCS=true` in `.env`, then restart the API container:

```bash
docker compose restart api   # or: podman compose restart api
```

- Swagger UI: **http://localhost:8000/docs**
- ReDoc: **http://localhost:8000/redoc**

### Logs

All services emit structured JSON logs. Each line includes `timestamp`, `level`, `logger`, `service`, `message`, and an `event` slug for machine parsing.

Frontend errors (`api_error`, `network_error`, `vue_error`, `unhandled_promise_rejection`) are written as structured JSON to `console.error` by `api/client.ts` and `main.ts`. In production, these appear in the `webrag-frontend` pod's stdout and are collected by Alloy → Loki.

The frontend HTML document title is `WebRAG` (browser tab title).

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

Every log line is JSON. Key fields: `timestamp`, `level`, `logger`, `service`, `event`, `message`.

```bash
# Follow all logs
podman compose logs -f api worker

# Filter to a specific event slug
podman compose logs api | grep '"event": "query_failed"'
podman compose logs api | grep '"event": "search_failed"'
```

Event catalogue:

| Event | Service | Meaning |
|-------|---------|---------|
| `http_request` | api | Every HTTP request — method, path, status, duration_ms, client |
| `http_error` | api | Unhandled exception before response was sent |
| `query_received` | api | /query endpoint received a request |
| `query_completed` | api | /query returned successfully |
| `query_failed` | api | /query raised a RuntimeError (→ 502) |
| `search_start` | api | Qdrant hybrid search starting |
| `search_complete` | api | Qdrant returned hits |
| `search_failed` | api | Qdrant unreachable or error |
| `llm_timeout` | api | LLM request timed out (180 s) |
| `llm_error` | api | LLM API returned an error status |
| `jwt_invalid` | api | JWT decode failed (expired or tampered) |
| `admin_created` | api | Bootstrap admin created on first startup |
| `scheduler_job_triggered` | api | Crawl job published to queue |
| `scheduler_crawl_failed` | api | Failed to publish crawl job |
| `scheduler_run_complete` | api | Scheduler tick finished |
| `experiment_started` | api | Experiment run started |
| `experiment_executing` | api | Running individual queries |
| `experiment_query_done` | api | Single experiment query complete |
| `experiment_completed` | api | Experiment finished with metrics |
| `experiment_failed` | api | Experiment raised an exception |
| `experiment_background_crashed` | api | Background task for experiment crashed |
| `presigned_url_failed` | api | S3 presigned URL generation failed |
| `ingest_started` | worker | Job picked up from queue |
| `ingest_completed` | worker | Full pipeline succeeded |
| `ingest_failed` | worker | Pipeline raised an exception |
| `ingest_strategy_attempt` | worker | Trying a scraping strategy |
| `ingest_strategy_fallback` | worker | Falling back to next strategy |
| `ingest_strategy_error` | worker | A strategy raised an error |
| `captcha_detected` | worker | CAPTCHA found during ingest — also fires `rag_app=incident` Loki label |
| `document_created` | worker | Document + chunks saved to DB |
| `embedding_completed` | worker | Chunks upserted into Qdrant |
| `embedding_failed` | worker | Qdrant upsert failed |
| `chunks_delete` | worker | Chunks deleted from Qdrant |
| `chunking_prose` | worker | Prose chunking complete (DEBUG) |
| `chunking_tables` | worker | Table chunking complete (DEBUG) |
| `chunking_vlm` | worker | VLM block chunking complete (DEBUG) |
| `worker_job_started` | worker | Message dequeued |
| `worker_job_completed` | worker | Job fully processed |
| `worker_job_incomplete` | worker | Job finished with non-done status |
| `worker_job_crashed` | worker | Unexpected exception in job |
| `worker_invalid_message` | worker | Malformed message dropped |
| `api_error` | frontend | API call returned a non-2xx status |
| `network_error` | frontend | fetch() failed (no network / DNS) |
| `vue_error` | frontend | Uncaught Vue component error |
| `unhandled_promise_rejection` | frontend | Unhandled JS promise rejection |

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

**API or worker is slow to start (15–45 s after Postgres is ready)**
→ Normal — BGE-M3 (~2.3 GB) is being loaded from disk into memory. Watch `podman compose logs -f api | grep '"event"'` and wait for `model_load_complete`. On the very first run it also downloads ~570 MB from Hugging Face before loading; subsequent starts use the `hf_cache` volume.

**API stays on "Waiting for Postgres/RabbitMQ"**
→ Give it 30–60 seconds on first run. Databases take time to initialize. The API and worker use a TCP socket poll loop that waits up to 100 s total before failing.

**Worker not processing jobs**
→ Check `podman compose logs worker`. If it shows import errors, run `podman compose build` again.

**Vision extraction fails**
→ Verify `VLM_BASE_URL`, `VLM_API_KEY`, and `VLM_MODEL` in `.env`. Test the endpoint with `curl -H "Authorization: Bearer $VLM_API_KEY" $VLM_BASE_URL/models`.

**S3 upload errors**
→ Verify `S3_ENDPOINT_URL`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`. For default local compose, ensure `minio` and `minio_init` containers are healthy and completed, and that `S3_BUCKET_EVIDENCE` (`rag-evidence-dev`) and `S3_BUCKET_DOCS` (`rag-documents-dev`) exist.

**Playwright/screenshot errors**
→ Screenshot strategy needs Chromium in the worker container. If it fails, rebuild: `docker compose build --no-cache worker`.

**Podman: RabbitMQ fails to start (erlang cookie permission denied)**
→ In Podman rootless, the RabbitMQ process runs as UID 999 (a subuid-mapped UID) while the container's UID 0 maps to your host user. The `docker-compose.yml` entrypoint wrapper pre-writes the erlang cookie as mode 400 before the main entrypoint runs. If you see `eacces` or "must be accessible by owner only" errors, ensure `rabbitmq_data` volume is clean: `podman compose down -v`.

---

## Project Structure

```text
app/
├── backend/          # FastAPI Python service — see docs/backend/README.md
├── frontend/         # Vue 3 + TypeScript SPA — see docs/frontend/README.md
├── tests/            # Pytest test suite — see docs/tests/README.md
├── docker-compose.yml
├── .env.example
└── docs/
    ├── backend/      # Backend architecture, data model, flows, services
    ├── frontend/     # Frontend views, components, routing, auth
    └── tests/        # Test structure, fixtures, coverage
```

**Detailed documentation:**

- **[Backend Documentation](docs/backend/README.md)** — directory structure, data model, ingest flow, RAG query flow, authentication, scheduler, logging, worker details, embedding model, metrics, recommended refactors
- **[Frontend Documentation](docs/frontend/README.md)** — directory structure, views, components, API client, authentication flow, styling, nginx configuration, TypeScript types, UI behavior notes
- **[Tests Documentation](docs/tests/README.md)** — test structure, fixtures, what is tested, running tests locally, CI status, adding new tests, troubleshooting
- **[CI/CD Documentation](docs/.github/README.md)** — GitHub Actions workflow, jobs (conventional commits, backend tests, frontend build, build-and-push), triggers, image tagging strategy

---

## Testing

See **[docs/tests/README.md](docs/tests/README.md)** for complete testing documentation.

**Quick start:**

```bash
cd backend
poetry install
poetry run pytest ../tests/ -v
```

### What is tested

| File | Covers |
|------|--------|
| `tests/test_api.py` | Health, metrics, auth (login, /me, stats), sources (list, SSRF guard), query auth gate, documents, incidents, chunker unit tests |
| `tests/test_config.py` | Settings loading from environment variables |

### Test fixtures (`tests/conftest.py`)

- `create_schema` — creates all DB tables once per session via `Base.metadata.create_all`
- `create_admin` — calls `ensure_admin_exists` so login tests have a real user
- `client` — async `httpx.AsyncClient` backed by ASGI transport (no real HTTP server needed)
- `auth_headers` — logs in as the default admin and returns the `Authorization` header dict

### Pending tests (TODO)

- Experiment endpoints — waiting for the feature to be implemented
- Ingest pipeline end-to-end — requires RabbitMQ and Qdrant; currently out of scope for unit tests
- RAG query with real embeddings — skipped because BGE-M3 is not loaded in CI

### CI status

`backend-tests` runs in GitHub Actions against PostgreSQL 16 on every PR/push. The image build job is gated on both backend tests and frontend build, so failed tests block image publishing immediately.

---

## CI / CD

See **[docs/.github/README.md](docs/.github/README.md)** for complete CI/CD documentation.

**GitHub Actions workflow:**
1. Conventional commits check
2. Backend tests (pytest against Postgres 16)
3. Frontend build (TypeScript check + Vite build)
4. Build & push images to GHCR (on `main`/`kost` push or semver tags only)

**Published images:**
- `ghcr.io/ass-nss-project/webrag-backend` — Monorepo image containing API + workers
  - Used by: API Deployment, ingest worker StatefulSet, embedding worker StatefulSet
  - Same image, different commands: `uvicorn main:app`, `python worker_ingest.py`, `python worker_embed.py`
- `ghcr.io/ass-nss-project/webrag-frontend` — Vue 3 / nginx SPA

**Image tags:**
- Branch: `main-<sha>`, `kost-<sha>` (automatic on push)
- Semver: `0.1.0`, `0.1`, `0` (manual: `git tag v0.1.0 && git push --tags`)

---

## Kubernetes (Production)

The production deployment lives in [ASS-NSS-Project/infra](https://github.com/ASS-NSS-Project/infra) (branch `kost`), managed by ArgoCD.

| Service | Production URL |
|---------|----------------|
| Main UI + API | <https://rag.nss.jkzl.eu> |
| RabbitMQ Management | <https://rabbitmq.nss.jkzl.eu> |

The API is accessible via the `/api` prefix on `rag.nss.jkzl.eu` — Traefik rewrites `/api/*` → `/*` before forwarding to the backend. This lets cURL clients target a stable public endpoint without needing to know the internal path layout.

The worker runs as a **StatefulSet** in Kubernetes (not a Deployment) because the BGE-M3 cache volume is `ReadWriteOnce`. Each replica gets its own `hf-cache` PVC; scaling workers means setting `replicas` to any positive integer — each pulls independently from the shared RabbitMQ queue.

**cURL example (production):**
```bash
# Obtain a JWT token
TOKEN=$(curl -s -X POST https://rag.nss.jkzl.eu/api/auth/login \
  -d "username=user@example.com&password=YOUR_PASSWORD" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Query the RAG system
curl -s -X POST https://rag.nss.jkzl.eu/api/query/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question": "What are the latest findings?", "top_k": 5}' \
  | python3 -m json.tool

# List available models
curl -s https://rag.nss.jkzl.eu/api/query/models \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

ArgoCD sync waves:

- Wave 19 — `rabbitmq-operator` (RabbitMQ Cluster Operator)
- Wave 20 — `qdrant` (Qdrant via Helm)
- Wave 19 — `webrag` (API, workers, frontend, CNPG Postgres, secrets via ESO/Vault)

Secrets are provisioned via `terraform/vault` in `infra/`. DNS records are managed via `terraform/cloudflare`.

For architectural recommendations and future refactoring considerations, see **[docs/backend/README.md](docs/backend/README.md#recommended-refactors)**.
