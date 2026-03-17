# RAG System — Multimodal Web Intelligence Platform

A production-ready system for scraping web content, extracting structured data with AI vision, and answering questions via RAG (Retrieval-Augmented Generation).

---

## What This System Does

1. **Ingests** websites using a multi-strategy pipeline:
   - HTML fetch → Rendered DOM (Playwright) → Screenshot + Claude Vision
2. **Extracts** structured content from screenshots using Claude claude-sonnet-4-6
3. **Indexes** content in Qdrant (vector database) for semantic search
4. **Answers** questions using RAG — finds relevant passages, then answers with citations
5. **Tracks** CAPTCHA incidents, audit logs, and evidence files

---

## Prerequisites

Install these before starting:

- **Docker Desktop**: https://www.docker.com/products/docker-desktop/
- **Git**: https://git-scm.com/
- **Anthropic API Key**: https://console.anthropic.com (create an account, go to API Keys)

---

## Setup (Step by Step)

### 1. Clone and enter the project

```bash
cd rag_system
```

### 2. Create your `.env` file

```bash
cp .env.example .env
```

Open `.env` in any text editor and fill in:

```env
ANTHROPIC_API_KEY=sk-ant-api03-...your-actual-key...
JWT_SECRET=any-long-random-string-here
FIRST_ADMIN_EMAIL=admin@example.com
FIRST_ADMIN_PASSWORD=choose-a-password
```

The other values (POSTGRES_PASSWORD, MINIO_ROOT_PASSWORD) can stay as-is for local development, but change them for anything exposed to the internet.

### 3. Start the system

```bash
docker compose up --build
```

This will:
- Download all Docker images (~5 minutes on first run)
- Build your API container (installs Python packages + Playwright/Chromium)
- Start all 6 services (PostgreSQL, Redis, MinIO, Qdrant, API, Worker)

You'll know it's ready when you see:
```
rag_api    | INFO: Startup complete. API ready.
rag_worker | INFO: Worker ready. Listening on queue: ingest
```

### 4. Open the UI

Go to: **http://localhost:8000**

Log in with the `FIRST_ADMIN_EMAIL` and `FIRST_ADMIN_PASSWORD` from your `.env`.

---

## Using the System

### Adding a Source

1. Click **Sources** in the sidebar
2. Click **Add Source**
3. Fill in the URL and select a strategy:
   - **HTML fetch**: for simple static sites (fastest)
   - **Rendered DOM**: for React/Vue/Angular apps
   - **Screenshot + AI**: for complex layouts, tables in images

### Triggering Ingest

1. In the Sources list, click **▶ Ingest** next to a source
2. A job is queued — the worker picks it up in seconds
3. Click **Jobs** to see status and which strategy was used

### Asking Questions

1. Click **Query** in the sidebar
2. Type your question
3. Choose mode:
   - **RAG**: retrieves relevant chunks first, then answers with citations *(recommended)*
   - **No-RAG**: asks Claude directly (for comparison)
4. Press **Ask** (or Ctrl+Enter)

### Handling CAPTCHA Incidents

When a scrape is blocked by CAPTCHA:
- An incident is automatically created
- Go to **Incidents** in the sidebar
- Click **Resolve** and enter a resolution note (e.g., "Switched source to API endpoint")

---

## Service URLs

| Service | URL | Purpose |
|---------|-----|---------|
| Main UI + API | http://localhost:8000 | Your app |
| Qdrant Dashboard | http://localhost:6333/dashboard | Browse vector collections |
| MinIO Console | http://localhost:9001 | Browse stored files (screenshots, HTML) |

MinIO login: `minioadmin` / `minioadmin` (or whatever you set in .env)

---

## Architecture Overview

```
User (Browser)
    │
    ▼
FastAPI (port 8000)
    │── Auth (JWT)
    │── Sources API
    │── Query API ──────────────► Qdrant (vectors)
    │── Incidents API               ▲
    │                               │ embed
    ▼                               │
Redis Queue ──────► Worker ─────────┘
                      │
                      ├── HTML fetch (httpx)
                      ├── Rendered DOM (Playwright/Chrome)
                      ├── Screenshot (Playwright)
                      │       └── Claude Vision (Anthropic API)
                      │
                      ├── PostgreSQL (metadata, jobs, audit)
                      └── MinIO (screenshots, HTML evidence)
```

---

## Development

### See logs
```bash
docker compose logs -f api      # API logs
docker compose logs -f worker   # Worker logs
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

### API Documentation (auto-generated)
FastAPI generates interactive API docs automatically:
- **http://localhost:8000/docs** — Swagger UI (test endpoints in browser)
- **http://localhost:8000/redoc** — ReDoc (cleaner reading)

---

## Troubleshooting

**"Cannot connect to Docker daemon"**
→ Start Docker Desktop first.

**API stays on "Waiting for Redis/Postgres"**
→ Give it 30-60 seconds on first run. Databases take time to initialize.

**Worker not processing jobs**
→ Check `docker compose logs worker`. If it shows import errors, run `docker compose build` again.

**Claude API errors**
→ Check your `ANTHROPIC_API_KEY` in `.env`. Make sure there's credit on the account.

**Playwright/screenshot errors**
→ These sometimes need more memory. In Docker Desktop settings, increase memory to at least 4GB.

---

## Project Structure

```
rag_system/
├── docker-compose.yml      # All services definition
├── .env.example            # Config template (copy to .env)
└── api/
    ├── Dockerfile          # Container build instructions
    ├── requirements.txt    # Python dependencies
    ├── main.py             # FastAPI app entry point
    ├── config.py           # Settings from environment
    ├── database.py         # DB connection setup
    ├── models.py           # All database tables
    ├── worker.py           # Background job processor
    ├── routers/
    │   ├── auth.py         # Login, register, /me
    │   ├── sources.py      # Source management + ingest trigger
    │   ├── query.py        # RAG query endpoint
    │   └── incidents.py    # CAPTCHA incident management
    ├── services/
    │   ├── ingest_service.py     # Core scraping pipeline
    │   ├── extraction_service.py # Claude vision extraction
    │   ├── embedding_service.py  # Sentence-transformers + Qdrant
    │   ├── rag_service.py        # RAG query engine
    │   ├── storage_service.py    # MinIO file storage
    │   ├── captcha_service.py    # CAPTCHA detection + incidents
    │   └── auth_service.py       # JWT + password hashing
    └── static/
        └── index.html      # Frontend UI
```
