# RAG System — Multimodal Web Intelligence Platform

A production-ready system for scraping web content, extracting structured data with AI vision, and answering questions via RAG (Retrieval-Augmented Generation).

Everything runs **fully locally** — no external AI API keys required. All LLM inference is handled by [Ollama](https://ollama.com/).

---

## What This System Does

1. **Ingests** websites using a multi-strategy pipeline:
   - HTML fetch → Rendered DOM (Playwright) → Screenshot + local vision AI
2. **Extracts** structured content from screenshots using a local vision-language model (`qwen3-vl:2b` via Ollama)
3. **Indexes** content in Qdrant (vector database) using local sentence-transformer embeddings (`BAAI/bge-m3`)
4. **Answers** questions using RAG — finds relevant passages, then answers with citations via a local LLM (`llama3.2:3b` via Ollama)
5. **Tracks** CAPTCHA incidents, audit logs, and evidence files

---

## Prerequisites

- **Docker Desktop**: https://www.docker.com/products/docker-desktop/
- **Git**: https://git-scm.com/
- At least **8 GB RAM** available to Docker (models are loaded into memory)
- A **GPU** is optional but recommended for faster inference (Ollama auto-detects NVIDIA GPUs)

---

## Setup (Step by Step)

### 1. Clone and enter the project

```bash
git clone <repository-url> rag_system
cd rag_system
```

### 2. Create your `.env` file

```bash
cp .env.example .env
```

Open `.env` in any text editor and fill in the required values:

```env
# Strong random passwords for local services
POSTGRES_PASSWORD=change_me_strong_password
RABBITMQ_DEFAULT_PASS=change_me_strong_password
MINIO_ROOT_PASSWORD=change_me_strong_password

# JWT signing secret — generate with:
# python -c "import secrets; print(secrets.token_hex(32))"
JWT_SECRET=your-random-hex-string

# First admin account (created automatically on first startup)
FIRST_ADMIN_EMAIL=admin@example.com
FIRST_ADMIN_PASSWORD=change_me_strong_password
```

#### Optional: Google OAuth2

To enable "Sign in with Google", also fill in:

```env
GOOGLE_CLIENT_ID=...your-client-id...
GOOGLE_CLIENT_SECRET=...your-client-secret...
GOOGLE_REDIRECT_URI=https://your-domain/auth/google/callback
FRONTEND_URL=https://your-domain
```

Create OAuth credentials at [Google Cloud Console](https://console.cloud.google.com/) under APIs & Services → Credentials.
Add `https://your-domain/auth/google/callback` to **Authorized redirect URIs**.

#### Optional: Custom Ollama models

The default models work out of the box. Override them in `.env` if you want different ones:

```env
OLLAMA_MODEL=llama3.2:3b           # Text LLM for RAG answers
OLLAMA_VISION_MODEL=qwen3-vl:2b   # Vision LLM for screenshot extraction
```

#### Production deployment

Set `DOMAIN` to your server's hostname or IP to enable Traefik routing. Once the domain resolves to your server, TLS certificates are obtained automatically from Let's Encrypt:

```env
DOMAIN=your-server-ip-or-domain
ACME_EMAIL=you@example.com
```

### 3. Create the Traefik certificate file

Traefik needs a writable file (not a directory) for TLS certificates. Git does not track it, so create it manually after cloning:

```bash
touch acme.json && chmod 600 acme.json
```

### 4. Start the system

```bash
# CPU-only (default):
docker compose up --build

# With NVIDIA GPU acceleration for Ollama:
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build
```

This will:
- Download all Docker images (~5–10 minutes on first run, Ollama image is large)
- Build the API and frontend containers
- Start all 9 services

You'll know it's ready when you see:
```
rag_api    | INFO: Startup complete. API ready.
rag_worker | INFO: Worker ready. Listening on queue: ingest
```

### 5. Pull the Ollama models

On first run, Ollama starts empty. Pull the models it needs:

```bash
docker exec rag_ollama ollama pull llama3.2:3b
docker exec rag_ollama ollama pull qwen3-vl:2b
```

This downloads ~2–4 GB of model weights. Only needed once — models are stored in a persistent Docker volume.

### 6. Open the UI

Go to: **http://localhost**

Log in with the `FIRST_ADMIN_EMAIL` and `FIRST_ADMIN_PASSWORD` from your `.env`.

---

## Using the System

### Adding a Source

1. Click **Sources** in the sidebar
2. Click **Add Source**
3. Fill in the URL and select a strategy:
   - **HTML fetch**: for simple static sites (fastest)
   - **Rendered DOM**: for React/Vue/Angular apps
   - **Screenshot + AI**: for complex layouts, tables in images, JS-heavy pages

### Triggering Ingest

1. In the Sources list, click **▶ Ingest** next to a source
2. A job is queued — the worker picks it up in seconds
3. Click **Jobs** to see status and which strategy was used

The system automatically re-crawls each source based on its `crawl_frequency_hours` setting (default: 24 hours).

### Asking Questions

1. Click **Query** in the sidebar
2. Type your question
3. Choose mode:
   - **RAG**: retrieves relevant chunks first, then answers with citations *(recommended)*
   - **No-RAG**: asks the LLM directly without retrieval (for comparison)
4. Press **Ask** (or Ctrl+Enter)

### Handling CAPTCHA Incidents

When a scrape is blocked by a CAPTCHA:
- An incident is automatically created with a screenshot of the block page
- Go to **Incidents** in the sidebar
- Click **Resolve** and enter a resolution note (e.g., "Switched source to API endpoint")

---

## Service URLs

| Service | URL | Notes |
|---------|-----|-------|
| Main UI | http://localhost | Frontend application |
| API | http://localhost (proxied) | FastAPI backend via Traefik |
| Swagger UI | disabled by default | Set `API_DOCS=true` in `.env` to enable |
| Qdrant Dashboard | http://localhost:6333/dashboard | Browse vector collections (localhost only) |
| MinIO Console | http://localhost:9001 | Browse stored files (localhost only) |
| RabbitMQ Management | http://localhost:15672 | Browse queues and messages (localhost only) |
| Ollama API | http://localhost:11434 | Local LLM inference (localhost only) |

MinIO login: `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` from your `.env`
RabbitMQ login: `RABBITMQ_DEFAULT_USER` / `RABBITMQ_DEFAULT_PASS` from your `.env`

> Admin ports (9001, 15672, 6333, 11434) are bound to `127.0.0.1` only and not exposed to the network.

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
            │── Query API ──────────────► Qdrant (vector search)
            │── Incidents API               ▲
            │── Audit API                   │ embed (BAAI/bge-m3)
            │                               │
            ▼                               │
       RabbitMQ Queue ──────► Worker ──────┘
                                  │
                                  ├── HTML fetch (httpx)
                                  ├── Rendered DOM (Playwright/Chrome)
                                  ├── Screenshot (Playwright)
                                  │       └── Vision LLM (qwen3-vl via Ollama)
                                  │
                                  ├── PostgreSQL (metadata, jobs, audit)
                                  └── MinIO (screenshots, HTML evidence)

All LLM inference: Ollama (local, no external API)
```

---

## Development

### Enable API docs

Set `API_DOCS=true` in your `.env`, then restart the API:

```bash
docker compose restart api
```

Swagger UI will be available at **http://localhost/docs** (or `http://localhost:8000/docs` if accessing the API directly).

### See logs

```bash
docker compose logs -f api      # API logs
docker compose logs -f worker   # Worker logs
docker compose logs -f frontend # Frontend/Nginx logs
docker compose logs -f ollama   # Ollama model server logs
```

### Restart a single service

```bash
docker compose restart api
```

### Stop everything

```bash
docker compose down             # Stop but keep data
docker compose down -v          # Stop AND delete all data (fresh start)
```

---

## Troubleshooting

**"Cannot connect to Docker daemon"**
→ Start Docker Desktop first.

**API stays on "Waiting for Postgres/RabbitMQ"**
→ Give it 30–60 seconds on first run. Databases take time to initialize.

**Worker not processing jobs**
→ Check `docker compose logs worker`. If it shows import errors, run `docker compose build` again.

**Vision extraction fails / returns empty**
→ Make sure `qwen3-vl:2b` was pulled: `docker exec rag_ollama ollama list`

**Ollama is slow**
→ By default it runs on CPU. On Linux with an NVIDIA GPU, the compose file enables GPU passthrough automatically. On Mac, Ollama uses Metal (GPU acceleration) inside the container.

**Out of memory errors**
→ Increase Docker's memory limit in Docker Desktop settings to at least 8 GB.

**Playwright/screenshot errors**
→ Screenshot strategy needs Chromium running inside the worker. If it fails, check `docker compose logs worker` for Playwright install errors and rebuild: `docker compose build --no-cache worker`.

---

## Project Structure

```
rag_system/
├── docker-compose.yml          # All 9 services
├── .env.example                # Config template (copy to .env)
├── acme.json                   # Traefik TLS certificate storage
├── backend/                    # FastAPI Python service
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py                 # App entry point, startup logic
│   ├── config.py               # Settings from environment variables
│   ├── database.py             # SQLAlchemy DB connection
│   ├── models.py               # All database tables (ORM)
│   ├── worker.py               # Background job processor (RabbitMQ consumer)
│   ├── alembic.ini             # Database migration config
│   ├── alembic/                # Migration scripts
│   ├── routers/
│   │   ├── auth.py             # Login, register, JWT tokens, audit log, user management
│   │   ├── auth_google.py      # Google OAuth2 (HMAC-signed stateless state tokens)
│   │   ├── sources.py          # Source management + ingest trigger (SSRF-protected)
│   │   ├── query.py            # RAG query endpoint
│   │   └── incidents.py        # CAPTCHA incident management
│   └── services/
│       ├── ingest_service.py     # Core scraping pipeline (3 strategies + fallback)
│       ├── extraction_service.py # Local vision LLM extraction via Ollama
│       ├── embedding_service.py  # BAAI/bge-m3 sentence-transformers + Qdrant
│       ├── rag_service.py        # RAG query engine (Ollama via OpenAI-compatible API)
│       ├── storage_service.py    # MinIO file storage
│       ├── captcha_service.py    # CAPTCHA detection + incident creation
│       ├── auth_service.py       # JWT + bcrypt password hashing
│       ├── scheduler_service.py  # APScheduler: periodic crawls + evidence cleanup
│       └── queue_service.py      # RabbitMQ job publisher
└── frontend/                   # Vue 3 + TypeScript SPA
    ├── Dockerfile
    ├── nginx.conf              # Nginx static file server with security headers
    ├── src/
    │   ├── main.ts             # App entry point + OAuth token handler
    │   ├── App.vue             # Root component
    │   ├── router/             # Vue Router (hash-based routing)
    │   ├── stores/             # Pinia state management (auth)
    │   ├── api/                # Axios API client + TypeScript types
    │   ├── views/              # Page components (Dashboard, Sources, Query,
    │   │                       #   Incidents, Audit, Users, Login)
    │   └── components/         # Reusable UI components
    └── package.json
```
