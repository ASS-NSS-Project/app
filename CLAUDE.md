# repo — CLAUDE.md

RAG (Retrieval-Augmented Generation) system. Scrapes web sources, embeds content into a vector database, and answers natural-language questions with citations.

**Stack:** FastAPI · Python 3.11 · Vue 3 + TypeScript · PostgreSQL 16 · Qdrant · RabbitMQ · Traefik · BGE-M3 (local embeddings) · OpenAI-compatible LLM/VLM (CERIT-SC AIaaS) · CESNET S3

---

## Directory structure

```
repo/
├── backend/                    # FastAPI application + worker
├── frontend/                   # Vue 3 SPA
├── tests/                      # Pytest suite
├── docs/                       # Architecture diagrams, ER diagram, API docs (LaTeX)
├── docker-compose.yml          # Production: all services, Let's Encrypt TLS via Traefik
├── docker-compose.override.yml # Local dev: HTTP-only, Podman-compatible
├── .env.example                # Config template
└── .github/workflows/ci.yml   # CI: tests → build → push to ghcr.io
```

---

## `backend/`

The FastAPI application and the background worker. Both run from the same Docker image (`backend/Dockerfile`) — the API via `uvicorn main:app`, the worker via `python worker.py`.

```
backend/
├── main.py               # App entry: lifespan hooks (migrations, admin creation, Qdrant init, scheduler), router registration, /health, /metrics
├── config.py             # All settings via env vars (pydantic-settings, lru_cache). Single source of truth.
├── database.py           # SQLAlchemy engine + SessionLocal + Base
├── models.py             # ORM table definitions (see Data Model below)
├── worker.py             # RabbitMQ consumer: pulls job_id → runs ingest pipeline → embeds chunks
├── alembic.ini           # Alembic config (script_location relative to main.py)
├── alembic/
│   ├── env.py            # Migration env (imports models, uses DATABASE_URL from env)
│   └── versions/
│       ├── 0001_baseline.py      # Initial schema
│       ├── 0002_add_username.py  # User.username column
│       ├── 0003_add_rq_job_id.py # IngestJob.rq_job_id column
│       ├── 0004_chunk_fields.py  # Extended Chunk metadata fields
│       └── 0005_experiments.py   # Experiment + ExperimentQuery tables
├── routers/
│   ├── auth.py           # POST /auth/login, /auth/register, GET /auth/me, /auth/users, stats, audit log
│   ├── auth_google.py    # GET /auth/google → OAuth2 flow → /auth/google/callback
│   ├── auth_keycloak.py  # GET /auth/keycloak → Keycloak OIDC → /auth/keycloak/callback
│   ├── sources.py        # CRUD /sources, POST /sources/{id}/ingest (SSRF-protected)
│   ├── query.py          # POST /query — RAG: embed → Qdrant hybrid search → LLM → citations
│   ├── documents.py      # GET /documents, /documents/{id}/chunks — browse indexed content + signed S3 URLs
│   ├── experiments.py    # POST /experiments, GET /experiments/{id} — batch RAG benchmarking
│   └── incidents.py      # GET/PATCH /incidents — CAPTCHA incident management
└── services/
    ├── ingest_service.py     # 3-strategy scrape pipeline (see Ingest flow below)
    ├── chunking.py           # split_prose / split_tables / split_vlm — structure-aware text splitting
    ├── extraction_service.py # VLM screenshot analysis via OpenAI-compatible AIaaS
    ├── embedding_service.py  # BGE-M3 (FlagEmbedding) + Qdrant hybrid search (dense + sparse, RRF)
    ├── rag_service.py        # Retrieve chunks from Qdrant → call LLM → build citation list
    ├── storage_service.py    # boto3: upload/download to CESNET S3, pre-signed URLs
    ├── captcha_service.py    # CAPTCHA heuristic detection (keyword list + Cloudflare signals)
    ├── auth_service.py       # JWT signing (python-jose), bcrypt hashing, ensure_admin_exists
    ├── scheduler_service.py  # APScheduler: check due sources every 5 min, queue ingest jobs
    ├── queue_service.py      # pika: publish job_id to RabbitMQ "ingest" queue
    ├── experiment_service.py # Run batch experiment queries, compute recall@k / MRR / nDCG
    ├── metrics.py            # prometheus_client: INGEST_JOBS_TOTAL, INGEST_DURATION, CAPTCHA_INCIDENTS_TOTAL
    └── logging_config.py     # python-json-logger structured JSON output for Loki
```

### Data model (`models.py`)

| Table | Purpose | Key columns |
|-------|---------|-------------|
| `users` | Accounts + roles | `role` (admin/curator/analyst/user), `oauth_provider`, `oauth_id` |
| `sources` | Monitored URLs | `base_url`, `preferred_strategy`, `crawl_frequency_hours`, `last_crawled_at` |
| `ingest_jobs` | One per scrape attempt | `status` (pending/running/done/failed/captcha_blocked), `strategy_used`, `quality_score` |
| `evidence` | Scraped artifacts (screenshots, HTML dumps) | `storage_uri` (S3 path), `file_hash`, `type` |
| `documents` | Extracted page content | `url`, `doc_version`, `content_uri`, `ingest_strategy`, `content_hash` |
| `chunks` | Text segments for vector search | `text`, `chunk_type` (text/table/block), `is_embedded`, `bounding_box`, `citation_evidence_id` |
| `incidents` | CAPTCHA / rate-limit / block events | `type`, `status` (open/in_progress/resolved), `evidence_screenshot_uri` |
| `audit_logs` | Immutable action log | `action`, `object_type`, `object_id`, `extra` (JSON) |
| `experiments` | Batch query benchmarks | `status`, `recall_at_k`, `mrr`, `ndcg`, `avg_latency_ms` |
| `experiment_queries` | Individual queries within an experiment | `query_text`, `expected_keywords`, per-query metrics |

All PKs are UUID strings. Migrations run automatically on API startup via Alembic (`_run_migrations()` in `main.py`) with up to 20 retries (guards against slow Postgres first-boot).

### Ingest flow

```
POST /sources/{id}/ingest
  → create IngestJob (status: pending)
  → publish {job_id} to RabbitMQ "ingest" queue

worker.py on_message()
  → process_ingest_job(job_id)
  → IngestService.run(job_id):

      Strategy 1 — HTML (httpx + BeautifulSoup)
        fetch URL → parse visible text → check len >= quality_threshold_chars (default 200)
        → CAPTCHA check (keyword scan of HTML)

      Strategy 2 — Rendered DOM (Playwright headless Chrome)
        launch browser → wait for JS → read DOM + take screenshot
        → CAPTCHA check

      Strategy 3 — VLM screenshot (ExtractionService)
        send screenshot to AIaaS vision model → get structured text back
        → CAPTCHA check

      If CAPTCHA detected at any step:
        → create Incident, set job status: captcha_blocked, upload screenshot to S3 evidence bucket

      If success:
        → save Document (text) to Postgres
        → split into Chunks (split_prose / split_tables / split_vlm)
        → upload screenshot + HTML to S3 docs bucket
        → set job status: done

  → _embed_job_chunks(db, job):
      → EmbeddingService.embed_chunks(db, doc.id)
      → BGE-M3 dense + sparse vectors per chunk
      → upsert into Qdrant (RRF hybrid scoring)
  → update source.last_crawled_at
```

### RAG query flow

```
POST /query {question, top_k, source_id?, strict_grounding}
  → embed question with BGE-M3 (dense + sparse)
  → Qdrant hybrid search: RRF fusion of dense + sparse results, top_k=5
  → chunks + question → LLM (CERIT-SC AIaaS, OpenAI-compatible)
      strict_grounding=true: system prompt forces LLM to use only retrieved context
  → build citations: pre-signed S3 URL per chunk evidence_id + relevance_score
  → return {answer, citations[]}
```

### Auth

- **JWT local** — `POST /auth/login` (username + password), 8-hour tokens (`JWT_EXPIRE_MINUTES=480`)
- **Google OAuth2** — `GET /auth/google` → consent → `/auth/google/callback` → JWT
- **Keycloak OIDC** — `GET /auth/keycloak` → Keycloak → `/auth/keycloak/callback` → JWT; realm roles map directly to `UserRole`
- **CORS** — only `FRONTEND_URL` is whitelisted
- **API docs** — `/docs` and `/redoc` disabled by default; set `API_DOCS=true` in `.env` to enable

### Scheduler

`scheduler_service.py` runs an APScheduler job every 5 minutes: scans `sources` where `is_active=true` and `last_crawled_at + crawl_frequency_hours <= now`, publishes an ingest job for each due source. Also runs an evidence retention cleanup job.

### Worker details

The worker processes one job at a time (`prefetch_count=1`). RabbitMQ heartbeat is set to 600 s to prevent disconnection during BGE-M3 model download (~570 MB, first boot only). The HuggingFace model cache is a shared Docker volume (`hf_cache`) — both the API and the worker mount it so the model is downloaded once.

---

## `frontend/`

Vue 3 SPA served by Nginx. Hash-based routing (`createWebHashHistory`). All API calls go to the same origin via Traefik path routing.

```
frontend/
├── src/
│   ├── main.ts           # App bootstrap, OAuth callback token handler (reads ?token= from URL)
│   ├── App.vue           # Root layout, JWT expiry listener
│   ├── router/index.ts   # Routes: /login (public), /dashboard, /sources, /query,
│   │                     #         /incidents, /audit, /users, /knowledge-base,
│   │                     #         /experiments, /jobs
│   ├── stores/
│   │   ├── auth.ts       # Pinia: JWT storage, isAuthenticated(), user info
│   │   └── query.ts      # Pinia: query history
│   ├── api/              # Axios client + TypeScript types for all API responses
│   ├── views/            # One .vue file per route (LoginView, DashboardView, SourcesView, …)
│   └── components/       # Shared: Layout, Sidebar, StatusBadge
├── nginx.conf            # Static file server: SPA fallback (try_files → index.html), security headers
├── Dockerfile            # node:20 build → nginx:alpine serve
└── vite.config.ts        # Dev proxy: /auth, /sources, /query, … → http://localhost:8000
```

In development (`npm run dev`), Vite proxies all API paths to `localhost:8000` so you can run the frontend standalone without Traefik.

---

## `tests/`

```
tests/
├── conftest.py      # Pytest fixtures: test DB (SQLite in-memory), FastAPI TestClient, override get_db
├── test_api.py      # Endpoint integration tests (auth, sources, query, incidents)
└── test_config.py   # Settings loading tests
```

CI runs these against a real Postgres 16 service container (not SQLite). Run locally:

```bash
cd backend
PYTHONPATH=. pytest ../tests/ -v
```

---

## `docs/`

Not user-facing documentation — these are project artefacts (LaTeX source, diagrams, Gantt charts). Do not edit unless updating the project report.

---

## Docker Compose

**Production** (`docker-compose.yml`):
- Traefik v3 with Let's Encrypt HTTP-01 (auto-cert when `DOMAIN` resolves to the server)
- HTTP → HTTPS redirect enabled
- Mounts `acme.json` (must be a file, not a directory — `touch acme.json && chmod 600 acme.json`)

**Local dev** (`docker-compose.override.yml`, merged automatically):
- Traefik HTTP-only, no TLS redirect, no ACME
- API and worker have TCP wait loops (guards against Postgres first-boot delay)
- Podman rootless fixes: SELinux `label=disable`, Erlang cookie chmod, configurable socket path via `DOCKER_SOCK`

Shared named volume `hf_cache` persists BGE-M3 weights across restarts — both `api` and `worker` mount it.

### Starting locally

```bash
cp .env.example .env
# fill in S3, LLM, VLM credentials; set API_DOCS=true for /docs

touch acme.json && chmod 600 acme.json   # required even in dev (Traefik mount)

podman compose up        # or: docker compose up
# UI:      http://localhost
# API:     http://localhost/auth, /sources, /query, …
# RabbitMQ mgmt: http://localhost:15672
```

---

## CI/CD (`.github/workflows/ci.yml`)

Triggers: PRs, pushes to `main`/`kost`, semver tags (`v*.*.*`).

| Job | What it does |
|-----|-------------|
| `commit-message-check` | pre-commit hook on commit messages |
| `backend-tests` | pytest against real Postgres 16 |
| `frontend-build` | `npm run build` + TypeScript type-check |
| `build-and-push` | Builds `rag-api` and `rag-frontend`, pushes to `ghcr.io/ass-nss-project/` |

Image tags:
- Branch push → `main-<short-sha>` or `kost-<short-sha>`
- Semver tag `v1.2.3` → `1.2.3` and `1.2`

The API image is reused for the worker in Kubernetes — the K8s Deployment overrides the command to `python worker.py`.

---

## Key env vars (see `.env.example` for full list)

| Variable | Purpose |
|----------|---------|
| `POSTGRES_*` | Database connection |
| `RABBITMQ_*` | Queue connection |
| `S3_*` | CESNET object storage (evidence + documents) |
| `LLM_BASE_URL / LLM_API_KEY / LLM_MODEL` | Text generation (CERIT-SC AIaaS) |
| `VLM_BASE_URL / VLM_API_KEY / VLM_MODEL` | Vision extraction (CERIT-SC AIaaS) |
| `JWT_SECRET` | Token signing — generate with `python -c "import secrets; print(secrets.token_hex(32))"` |
| `FIRST_ADMIN_*` | Bootstrap admin created on first startup |
| `KEYCLOAK_*` | Optional Keycloak OIDC (production SSO) |
| `DOMAIN` | Hostname for Traefik routing and Let's Encrypt |
| `API_DOCS` | `true` to enable `/docs` and `/redoc` (off by default) |
| `DOCKER_SOCK` | Podman socket path (e.g. `/run/user/1000/podman/podman.sock`) |
