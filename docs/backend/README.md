# Backend Documentation

FastAPI-based RAG system backend with RabbitMQ worker for asynchronous ingestion.

---

## Directory Structure

```text
backend/
├── main.py                 # App entry point, lifespan hooks (DB schema init, admin creation, Qdrant init, scheduler)
├── config.py               # All settings via env vars (pydantic-settings, lru_cache)
├── database.py             # SQLAlchemy engine + SessionLocal + Base
├── models.py               # ORM table definitions (see Data Model below)
├── worker_ingest.py               # RabbitMQ consumer: pulls job_id → runs ingest pipeline → embeds chunks
├── Dockerfile              # Multi-stage build: Poetry deps → FastAPI/worker container
├── pyproject.toml          # Poetry dependency manifest (uses pytorch-cpu supplemental source)
├── poetry.lock             # Locked dependency tree
├── routers/
│   ├── auth.py             # POST /auth/login, /auth/local-login, GET /auth/me, /auth/refresh, /auth/stats, /auth/providers
│   ├── auth_keycloak.py    # GET /auth/keycloak → Keycloak OIDC → /auth/keycloak/callback
│   ├── sources.py          # CRUD /sources, POST /sources/{id}/ingest (SSRF-protected), GET /sources/pipeline/stats, /sources/jobs/all
│   ├── query.py            # POST /query, GET /query/models — RAG: embed → Qdrant hybrid search → LLM → citations
│   ├── documents.py        # GET /documents, /documents/{id}/chunks, /documents/{id}/markdown — browse indexed content + signed S3 URLs
│   ├── experiments.py      # POST /experiments, GET /experiments/{id} — batch RAG benchmarking (scaffolded, not exposed yet)
│   └── incidents.py        # GET /incidents, POST /incidents/{id}/resolve, POST /incidents/simulate — CAPTCHA incident management
└── services/
    ├── ingest.py           # 4-strategy scrape pipeline: api/feed (Jina.ai + RSS) → html → rendered → screenshot+VLM
    ├── chunking.py         # split_prose / split_tables / split_vlm — token-measured text splitting
    ├── extraction.py       # VLM screenshot analysis via OpenAI-compatible AIaaS
    ├── embedding.py        # BGE-M3 FlagEmbedding + Qdrant hybrid search (dense + sparse, RRF fusion)
    ├── rag.py              # RAG query engine: Qdrant → multi-provider LLM (AIaaS/OpenAI/Gemini/Anthropic) → citations
    ├── storage.py          # CESNET S3 upload/download via boto3 + pre-signed URL generation
    ├── captcha.py          # CAPTCHA detection (keyword list + Cloudflare signals) + incident creation
    ├── auth.py             # JWT signing (python-jose), bcrypt hashing, ensure_admin_exists
    ├── scheduler.py        # APScheduler: periodic crawls every 5 min, cleanup, gauge refresh
    ├── queue.py            # pika: publish job_id to RabbitMQ "ingest" queue
    ├── experiment.py       # Run batch experiment queries, compute recall@k / MRR / nDCG
    ├── metrics.py          # prometheus_client: counters (jobs, queries, embeddings, CAPTCHA), histograms (latency), gauges (sources, incidents, Qdrant size)
    └── logging_config.py   # Structured JSON logging (python-json-logger, setup_logging() must be called early)
```

---

## Data Model

All tables are defined in `models.py`. PKs are UUID strings. Database tables are initialized on API startup via `Base.metadata.create_all()` in `main.py` with up to 20 retries (guards against slow Postgres first-boot).

| Table | Purpose | Key columns |
|-------|---------|-------------|
| `users` | Accounts + roles | `role` (admin/curator/analyst/user), `oauth_provider`, `oauth_id` |
| `sources` | Monitored URLs | `base_url`, `preferred_strategy`, `crawl_frequency_hours`, `last_crawled_at` |
| `ingest_jobs` | One per scrape attempt | `status` (pending/running/done/failed/captcha_blocked), `strategy_used`, `quality_score` |
| `evidence` | Scraped artifacts (screenshots, HTML dumps) | `storage_uri` (S3 path), `file_hash`, `type` |
| `documents` | Extracted page content | `url`, `doc_version`, `markdown_uri`, `chunks_uri`, `ingest_strategy`, `content_hash` |
| `chunks` | Text segments for vector search | `text`, `chunk_type`, `embedding_status`, `qdrant_sync_status`, `text_vector` (TSVECTOR), `retry_count` |
| `incidents` | CAPTCHA / rate-limit / block events | `type`, `status` (open/in_progress/resolved), `evidence_screenshot_uri` |
| `audit_logs` | Immutable action log | `action`, `object_type`, `object_id`, `extra` (JSON) |
| `experiments` | Batch query benchmarks | `status`, `recall_at_k`, `mrr`, `ndcg`, `avg_latency_ms` |
| `experiment_queries` | Individual queries within an experiment | `query_text`, `expected_keywords`, per-query metrics |

**Key changes:**
- `documents.markdown_uri` / `chunks_uri` — S3 paths for resilient storage
- `chunks.embedding_status` — tracks embedding lifecycle (pending → in_progress → done | failed)
- `chunks.qdrant_sync_status` — tracks Qdrant sync state (missing → synced | out_of_sync)
- `chunks.text_vector` — PostgreSQL TSVECTOR for keyword fallback search

---

## Ingest Flow (Async Architecture)

### Phase 1: Ingest (30 seconds — returns immediately)

```text
POST /sources/{id}/ingest
  → create IngestJob (status: pending)
  → publish {job_id} to RabbitMQ "ingest" queue

worker_ingest.py (ingest worker) on_message()
  → process_ingest_job(job_id)
  → IngestService.run(job_id):

      Strategy 0 — RSS/Atom feed (api)
        Jina.ai reader + RSS fallback → markdown

      Strategy 1 — HTML (httpx + BeautifulSoup)
        fetch URL → parse visible text → markdownify → markdown
        → CAPTCHA check (keyword scan of HTML)

      Strategy 2 — Rendered DOM (Playwright headless Chrome)
        launch browser → wait for JS → read DOM → markdownify → markdown
        → take screenshot → CAPTCHA check

      Strategy 3 — VLM screenshot (ExtractionService)
        take screenshot → send to AIaaS vision model → get structured text
        → CAPTCHA check

      If CAPTCHA detected at any step:
        → create Incident, set job status: captcha_blocked, upload screenshot to S3

      If success:
        → process markdown via markdownify (standardize format)
        → split into Chunks (split_prose / split_tables / split_vlm)
        → serialize chunks to JSON
        → upload to S3: document.md + chunks.json + metadata.json
        → create Document (markdown_uri, chunks_uri set)
        → create Chunks (embedding_status='pending', qdrant_sync_status='missing')
        → save to Postgres
        → set job status: done

  → _queue_embedding_job(db, job):
      → publish {document_id} to RabbitMQ "embeddings" queue
      → return immediately (embedding happens async)
  → update source.last_crawled_at
```

**User sees:** Ingest completes in 30 seconds. Content is immediately queryable via keyword search (Postgres full-text).

### Phase 2: Embedding (1-5 minutes — background worker)

```text
worker_embed.py (embedding worker) on_message()
  → process_embedding_job(document_id)
  → load Chunks WHERE embedding_status IN ('pending', 'failed')
  → mark chunks as 'in_progress', increment retry_count
  → batch embed using BGE-M3 (dense + sparse vectors)
  → build PointStruct for each chunk
  → upsert to Qdrant (wait=True)
  → optional: backup embeddings to S3 (if ENABLE_EMBEDDING_BACKUP_S3=true)
  → mark chunks as 'done':
      - embedding_status='done'
      - embedded_at=NOW()
      - qdrant_sync_status='synced'
      - qdrant_synced_at=NOW()
      - is_embedded=True (legacy)
  → commit to Postgres

  If error:
    → mark chunks as 'failed', set embedding_error
    → requeue if retry_count < 3
```

**User sees:** After 1-5 minutes, queries now use vector search (faster, better relevance).

**Worker recovery behavior:** If a RabbitMQ message is redelivered after a worker restart, the worker resumes `running` jobs and retries the embedding step for `done` jobs to prevent drift.

**Qdrant/Postgres drift handling:** Background heal service runs every 15-30 minutes to detect and fix drift automatically.

---

## RAG Query Flow (with Fallback)

```text
POST /query {question, top_k, source_id?, strict_grounding, mode, upstream_base_url?, upstream_api_key?, upstream_model?}
  
  → check Qdrant health (ping collection)
  
  IF Qdrant healthy:
    → embed question with BGE-M3 (dense + sparse)
    → Qdrant hybrid search: prefetch 50 dense + 50 sparse, RRF fusion, return top_k
    → mode='rag'
  
  ELSE (Qdrant down OR no results):
    → fallback to Postgres full-text search:
      - convert question to tsquery
      - search chunks.text_vector using ts_match()
      - rank by ts_rank(), return top_k
    → mode='keyword_fallback', warning='Vector search unavailable, using keyword fallback'
  
  → chunks + question → LLM (AIaaS / OpenAI / Gemini / Anthropic)
      strict_grounding=true: system prompt forces LLM to use only retrieved context
  → _strip_thinking(): remove <think>…</think> tags from response
  → build citations: url + truncated text + relevance_score per chunk
  → return {answer, citations[], chunks_retrieved, mode, warning?}
```

**Resilience:**
- Qdrant down? Falls back to keyword search automatically (no 502 errors)
- New sources? Keyword search works immediately, vectors ready in 1-5 minutes
- Embedding fails? Heal service retries automatically (max 3 attempts)

The `GET /query/models` endpoint returns the list of available LLM models. AIaaS models are always present; external provider models (OpenAI, Gemini, Anthropic) are included only when the corresponding API key is configured in the backend environment. The frontend uses this list to populate the model selector — no API keys are ever sent to or stored by the frontend.

---

## Sync & Heal Service

**File:** `services/sync.py`

Background service that automatically detects and fixes drift between Postgres and Qdrant. Runs as scheduled jobs via APScheduler.

### Jobs

| Job | Interval | Purpose |
|-----|----------|---------|
| **heal_pending_embeddings** | 5 min | Finds chunks stuck in `pending` status for >10 minutes and requeues them |
| **heal_failed_embeddings** | 15 min | Retries `failed` embeddings if retry_count < 3 |
| **detect_qdrant_drift** | 15 min | Compares Postgres count (embedding_status='done') with Qdrant count, alerts if >10% difference |
| **heal_qdrant_sync** | 30 min | Finds chunks marked as `done` but `qdrant_sync_status != 'synced'` and requeues for re-embedding |

### Drift Detection

```python
postgres_count = count(chunks WHERE embedding_status='done')
qdrant_count = qdrant.count('rag_chunks')
drift_pct = abs(postgres_count - qdrant_count) / postgres_count * 100

if drift_pct > 10%:
  logger.warning("Qdrant drift detected")
  if AUTO_RESYNC_ON_DRIFT:
    heal_qdrant_sync()  # Trigger automatic resync
```

**Configuration:**
- `HEAL_INTERVAL_MINUTES=15` — how often heal jobs run
- `DRIFT_ALERT_THRESHOLD_PCT=10.0` — alert threshold for drift
- `AUTO_RESYNC_ON_DRIFT=true` — auto-trigger resync when drift detected

---

## Authentication

- **JWT local** — `POST /auth/login` (username + password), 8-hour tokens (`JWT_EXPIRE_MINUTES=480`)
- **JWT password-only** — `POST /auth/local-login` (password only, used by UI login form for admin account)
- **Keycloak OIDC** — `GET /auth/keycloak` → Keycloak → `/auth/keycloak/callback` → JWT; realm roles map to `UserRole`
- **Opaque API token** — `POST /auth/api-token` generates a `secrets.token_urlsafe(32)` token, stores its SHA-256 hash on the `users` row, and returns the plaintext once. Any endpoint accepts `Authorization: Bearer <token>` with the opaque value. Expired tokens return `401 "API token expired"`. Lifetime is `API_TOKEN_EXPIRE_HOURS` (default `2160` = 90 days).
- **CORS** — only `FRONTEND_URL` is whitelisted
- **API docs** — `/docs` and `/redoc` disabled by default; set `API_DOCS=true` in `.env` to enable

User management (create, edit roles, deactivate) is done directly in Keycloak. Keycloak group membership maps to RAG roles: `admin`/`webrag_admin` → `webrag_admin`, `webrag_curator` → `webrag_curator`, `webrag_analyst` → `webrag_analyst`, `webrag_user` → `webrag_user`.

The `POST /auth/refresh` endpoint re-issues a JWT with the current DB role. Called by the frontend when a role mismatch is detected (e.g. after a Keycloak group change).

`GET /auth/api-token/status` returns `{has_token, expires_at, is_expired}` without revealing the token value. `POST /auth/api-token` generates or replaces the token (audit-logged as `API_TOKEN_GENERATED`). New columns on `users`: `api_token_hash` (SHA-256 hex, indexed), `api_token_created_at`, `api_token_expires_at`.

---

## Scheduler

`scheduler_service.py` runs an APScheduler job every 5 minutes: scans `sources` where `is_active=true` and `last_crawled_at + crawl_frequency_hours <= now`, publishes an ingest job for each due source. Also runs an evidence retention cleanup job and a gauge refresh job that updates Prometheus metrics (`rag_active_sources`, `rag_open_incidents`, `rag_qdrant_collection_size`) every 5 minutes.

---

## Logging Architecture

All backend services emit **structured JSON** via `python-json-logger` (configured in `services/logging_config.py`). Every log record includes `service`, `level`, `logger`, `timestamp`, `message`, and an `event` slug for Loki queries.

**Critical invariants — do not break these:**

- `setup_logging()` must be called at the top of `main.py` and `worker_ingest.py` before anything else imports `logging`.
- `HF_HUB_DISABLE_PROGRESS_BARS=1` must be set in every environment (K8s Deployment env, `.env`) — otherwise HuggingFace tqdm bars print raw text to stdout and pollute structured logs.
- Every module that can execute independently (routers, services, worker tasks) must have its own `logger = logging.getLogger(__name__)` and log entry/exit/error with an `event` slug.
- HTTP middleware in `main.py` logs every request/response (`event: http_request`). Skips `/health` and `/metrics` to avoid noise.

**Standard `event` slugs** (used in Loki queries):

| event | where | meaning |
|-------|-------|---------|
| `startup` / `shutdown` | main.py lifespan | API startup/shutdown |
| `http_request` | HTTP middleware | Every HTTP request — method, path, status, duration_ms, client |
| `http_error` | main.py middleware | Unhandled exception before response was sent |
| `query_received` / `query_completed` / `query_failed` | routers/query.py | RAG query lifecycle |
| `search_start` / `search_complete` / `search_failed` | embedding_service.py | Qdrant search |
| `model_load_start` / `model_load_complete` | embedding_service.py | BGE-M3 model loading |
| `embedding_completed` / `embedding_failed` | embedding_service.py | Chunk embedding |
| `jwt_invalid` | auth_service.py | JWT decode failed |
| `chunks_delete` | embedding_service.py | Chunks deleted from Qdrant |
| `admin_created` | auth_service.py | Bootstrap admin created on first startup |
| `scheduler_job_triggered` / `scheduler_crawl_failed` / `scheduler_run_complete` | scheduler.py | Scheduler activity |
| `experiment_started` / `experiment_executing` / `experiment_query_done` / `experiment_completed` / `experiment_failed` / `experiment_background_crashed` | experiment.py | Experiment lifecycle |
| `presigned_url_failed` | storage.py | S3 presigned URL generation failed |
| `ingest_started` / `ingest_completed` / `ingest_failed` | worker_ingest.py | Job lifecycle |
| `ingest_strategy_attempt` / `ingest_strategy_fallback` / `ingest_strategy_error` | ingest.py | Strategy execution |
| `captcha_detected` | captcha.py | CAPTCHA found — also fires `webrag=incident` Loki label |
| `document_created` | worker_ingest.py | Document + chunks saved to DB |
| `worker_job_started` / `worker_job_completed` / `worker_job_incomplete` / `worker_job_crashed` / `worker_invalid_message` | worker_ingest.py | Worker message handling |
| `chunking_prose` / `chunking_tables` / `chunking_vlm` | chunking.py | Chunking complete (DEBUG level) |
| `llm_timeout` / `llm_error` | rag.py | LLM request failures |

---

## Worker Details

### Ingest Worker (`worker_ingest.py`)

**Purpose:** Scrapes web content and stores to S3/Postgres (fast, 30 seconds).

- **Queue:** `"ingest"`
- **Processes:** One job at a time (`prefetch_count=1`)
- **Heartbeat:** 600 s (prevents disconnection during long scrapes)
- **Output:** Document + Chunks in Postgres, markdown + chunks.json in S3
- **Next step:** Publishes document_id to `"embeddings"` queue

### Embedding Worker (`worker_embed.py`)

**Purpose:** Embeds chunks and indexes in Qdrant (background, 1-5 minutes).

- **Queue:** `"embeddings"`
- **Processes:** One document at a time (`prefetch_count=1`)
- **Heartbeat:** 600 s (prevents disconnection during BGE-M3 model download)
- **Model:** BGE-M3 (BAAI/bge-m3, fp16) — ~2.3 GB loaded
- **Retry:** Requeues failed jobs up to 3 times
- **Output:** Vectors in Qdrant, chunks marked as `embedding_status='done'`
- **Metrics port:** 9091 (separate from ingest worker)

### Docker Volumes

- `api` — BGE-M3 cache for API (query-time embedding)
- `worker` — BGE-M3 cache for ingest worker (unused, kept for compatibility)
- `worker_embed` — BGE-M3 cache for embedding worker (actual embedding work)

Each worker has its own cache volume so the model is downloaded once per container.

### Kubernetes Deployment

In Kubernetes, both workers run as **StatefulSets** (not Deployments) because the BGE-M3 cache volume is `ReadWriteOnce`. Each replica gets its own `hf-cache` PVC; scaling workers means setting `replicas` to any positive integer — each pulls independently from the shared RabbitMQ queues.

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

---

## Build Time

Dependencies are managed with **Poetry** (`pyproject.toml` + `poetry.lock`). `sentence-transformers` and `FlagEmbedding` transitively depend on PyTorch. The `pytorch-cpu` supplemental source in `pyproject.toml` pins torch to the CPU-only wheels (~250 MB) instead of the default CUDA variant (~2 GB). The Dockerfile sets `POETRY_VIRTUALENVS_CREATE=false` so Poetry installs directly into the system Python (appropriate for containers). The BuildKit cache mount (`--mount=type=cache,target=/root/.cache/pypoetry`) keeps downloaded wheels across rebuilds.

**Local dev setup:**
```bash
cd backend
poetry install          # installs all deps including dev (pytest etc.)
poetry shell            # activate the virtualenv
```

After adding or updating dependencies, run `poetry lock` to regenerate `poetry.lock` and commit both files.

---

## Metrics

The `/metrics` endpoint exposes Prometheus metrics (no authentication). Scraped by the `webrag-api` ServiceMonitor (`infra/argocd/apps/webrag/config/webrag-api-ServiceMonitor.yaml`) every 30 s.

**Exported metrics:**

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

## Recommended Refactors

The current backend is a **monolith**: the same image runs both the FastAPI service (`uvicorn main:app`) and the RabbitMQ consumer (`python worker_ingest.py`). Both processes load BGE-M3 (~2.3 GB) into memory independently because every replica needs the model for either embedding (worker) or query-time embedding (API).

### Split the embedding service into its own microservice

**Motivation:**

- **Memory**: today each API replica + each worker replica holds its own BGE-M3 weights. With N API and M worker pods that is `(N + M) × 2.3 GB`. A single embedding service would hold one copy.
- **Independent scaling**: embedding is CPU-bursty (worker batches), the API is light and steady. They have very different resource profiles and should scale independently.
- **Fast API startup**: today login (and every other endpoint) waits 15–45 s for BGE-M3 to load in the lifespan startup. An embedding microservice removes that dependency from the API entirely.
- **Model upgrades**: swapping the embedding model becomes a deploy of one service, not a full backend rebuild.

**Trade-offs:**

- **Network overhead**: every query and every chunk batch becomes an RPC. Negligible at low QPS, real cost at scale — needs batching, timeouts, retries.
- **Operational surface**: one more pod to monitor, alert on, and recover. Requires a circuit breaker so an embedding outage degrades gracefully instead of taking the API down.
- **Code complexity**: define a stable HTTP/gRPC contract, serialise tensors, version the API.

**When to do it:** when the project moves beyond student-scale traffic (e.g., dozens of QPS, more than a handful of worker replicas) or when the model needs to change frequently.

### Cheaper interim fix — background model loading

Until the split is justified, the startup-blocking problem can be solved without architectural change:

- Move `get_embedding_model()` out of the FastAPI lifespan startup
- Spawn it as a background `asyncio.to_thread` task that records a `model_ready` future
- Have `/query` and embedding-touching endpoints `await` that future on first call
- Keep the synchronous load in `worker_ingest.py` — workers can block, no user is waiting

This keeps the monolith but makes login (and all non-embedding endpoints) responsive within seconds of container start, matching the behaviour you would get from a separate embedding service.

---

## Resilience Features

### 5-Minute SLA

New sources are queryable within 5 minutes:
- **Ingest completes in 30 seconds** — stores to S3/Postgres
- **Keyword fallback works immediately** — Postgres full-text search on `chunks.text_vector`
- **Vector embeddings complete in background** — 1-5 minutes via `worker_embed.py`

### Automatic Healing

Background jobs run every 5-30 minutes (see `services/sync.py`):
- **Detect stuck pending embeddings** → requeue after 10 minutes
- **Detect failed embeddings** → retry (max 3 attempts)
- **Detect Qdrant drift** → alert if >10% difference, trigger bulk resync if enabled
- **Heal out-of-sync chunks** → re-embed chunks marked as done but not synced

### Fallback Search

If Qdrant is down or unreachable:
- Queries automatically fall back to **Postgres full-text search** using `tsvector`
- Response includes `mode: "keyword_fallback"` and `warning: "Vector search unavailable"`
- **No 502 errors** — degraded but functional
- Keyword search uses English language stemming and stop words (Postgres `english` config)

**Enable/disable:** Set `ENABLE_KEYWORD_FALLBACK=true` in `.env` (enabled by default)

### S3 as Source of Truth

All content is stored in S3 for disaster recovery:

```
s3://rag-documents/{source_id}/{job_id}/
  document.md       # Processed markdown (via markdownify)
  chunks.json       # All chunks with metadata
  metadata.json     # Job metadata (strategy, quality_score, timestamps)

s3://rag-embeddings/{chunk_id}/  # Optional, if ENABLE_EMBEDDING_BACKUP_S3=true
  dense.npy         # Dense vector (NumPy array, 1024 floats)
  sparse.npz        # Sparse vector (compressed)
```

**Qdrant is rebuilable:**
- Delete collection? Heal service will re-embed from Postgres within 30 minutes
- Embedding backups in S3? Restore without re-embedding (if enabled)
- Database lost? Reconstruct from S3 chunks.json files

### Configuration

**New environment variables:**

```env
# Embedding
EMBEDDING_TIMEOUT_MINUTES=5
ENABLE_EMBEDDING_BACKUP_S3=false
S3_BUCKET_EMBEDDINGS=rag-embeddings

# Fallback
ENABLE_KEYWORD_FALLBACK=true
FALLBACK_SEARCH_ENGINE=postgres_tsvector
QDRANT_HEALTH_CHECK_TIMEOUT=2.0

# Healing
HEAL_INTERVAL_MINUTES=15
DRIFT_ALERT_THRESHOLD_PCT=10.0
AUTO_RESYNC_ON_DRIFT=true
```

### Setup Full-Text Search

Run once after upgrading to enable keyword fallback:

```bash
psql $DATABASE_URL < backend/scripts/setup_tsvector.sql
```

This creates:
- Trigger function `chunks_text_vector_update()`
- Trigger on `chunks` table (auto-updates `text_vector` on insert/update)
- GIN index on `text_vector` for fast full-text search
- Backfills existing rows

---

## Authentication
