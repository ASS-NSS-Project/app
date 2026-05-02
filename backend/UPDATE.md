# Backend — Relationship to ASS-NSS-Project/repo

This document describes how the backend in this project compares to the
reference repo, so contributors from that codebase can quickly understand
the differences.

---

## What is the same

- **FastAPI** application with the same dependency-injection patterns.
- **SQLAlchemy** ORM (v2 style).
- **Pydantic v2** settings and schemas.
- Routers registered in `main.py`, same CORS middleware setup.
- `/health` endpoint.

---

## What is different / extended

### Technology stack

| Aspect | Reference repo | This project |
|--------|---------------|--------------|
| DB | SQLite (demo) | **PostgreSQL** (production) |
| Schema setup | `Base.metadata.create_all` | `Base.metadata.create_all` (startup retries until Postgres is ready) |
| Deps | Poetry + `pyproject.toml` | **pip + `requirements.txt`** |
| Python | ≥ 3.13 | 3.11 (Docker image) |
| RAG core | `src/example_raglib/` (spaCy in-memory) | `services/` (sentence-transformers + **Qdrant**) |

### Additional services

This project adds the following infrastructure beyond the reference repo:

- **RabbitMQ** — async ingest job queue (`services/queue_service.py`,
  `worker.py`).
- **CESNET S3** — S3-compatible evidence file storage via boto3
  (`services/storage_service.py`).
- **Qdrant** — vector database for semantic search
  (`services/embedding_service.py`).
- **CERIT-SC AIaaS** — OpenAI-compatible LLM and VLM inference endpoints
  (`services/rag_service.py`, `services/extraction_service.py`).
- **APScheduler** — crawl scheduling (`services/scheduler_service.py`).

### Additional routers

| Router | Purpose |
|--------|---------|
| `routers/auth.py` | JWT login, registration, user management, audit log |
| `routers/auth_google.py` | Google OAuth2 flow |
| `routers/auth_keycloak.py` | Keycloak OIDC flow |
| `routers/sources.py` | Source CRUD + ingest triggering |
| `routers/query.py` | RAG / no-RAG query endpoint |
| `routers/documents.py` | Document and chunk browsing, signed S3 evidence URLs |
| `routers/experiments.py` | Batch RAG benchmarking (recall@k, MRR, nDCG) |
| `routers/incidents.py` | CAPTCHA incident management |

### Why `requirements.txt` instead of Poetry

The project predates the reference repo and runs in Docker containers where
plain `pip install -r requirements.txt` is simpler and faster than Poetry.
Migration to Poetry is possible but not required by the current deployment.

---

## Running locally

```bash
# requires all services running (see docker-compose.yml)
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```
