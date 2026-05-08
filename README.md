# WebRAG — Multimodal RAG Platform

WebRAG is a production RAG application for collecting web content, extracting structured knowledge, indexing it with hybrid embeddings, and answering natural-language questions with citations.

The system is built for the ASS-NSS Kubernetes platform but can run locally with Docker or Podman Compose. Text and vision inference use OpenAI-compatible endpoints such as CERIT-SC AIaaS; embeddings run locally with BGE-M3.

## What It Does

- Scrapes and normalizes web pages through a strategy waterfall: Jina.ai/API feed, raw HTML, rendered DOM, and screenshot plus VLM extraction.
- Stores extracted markdown, chunks, evidence, jobs, audit logs, and incidents in Postgres and S3-compatible object storage.
- Embeds chunks asynchronously with BGE-M3 dense and sparse vectors and stores them in Qdrant.
- Answers questions through RAG with citations, strict grounding support, and Postgres full-text fallback when Qdrant is unavailable.
- Tracks CAPTCHA and block incidents for curator review.
- Exposes Prometheus metrics and structured JSON logs for production monitoring.

## Architecture

```text
Browser
  -> Vue 3 frontend served by nginx
  -> FastAPI API
       |-- Auth: local JWT/API token + optional Keycloak OIDC
       |-- Sources, documents, incidents, experiments, query APIs
       |-- Scheduler and heal jobs
       |-- RAG query path -> Qdrant hybrid search or Postgres keyword fallback
       |-- LLM/VLM calls -> OpenAI-compatible inference endpoint
  -> RabbitMQ
       |-- ingest queue -> worker_ingest.py
       |-- embeddings queue -> worker_embed.py

Storage:
  PostgreSQL 16: metadata, users, jobs, documents, chunks, audit logs
  S3/MinIO/CESNET S3: evidence, markdown, chunk JSON, optional vector backups
  Qdrant: rebuildable hybrid vector index
```

## Runtime Components

| Component | Technology | Purpose |
|-----------|------------|---------|
| API | FastAPI, SQLAlchemy | Auth, source management, query, documents, incidents, metrics |
| Ingest worker | Python, Playwright, BeautifulSoup, VLM client | Scrape pages and create documents/chunks |
| Embedding worker | Python, FlagEmbedding BGE-M3 | Embed chunks and upsert dense+sparse vectors to Qdrant |
| Frontend | Vue 3, TypeScript, Pinia, PrimeVue | Role-aware operator and analyst UI |
| Database | PostgreSQL 16 | System source of truth |
| Queue | RabbitMQ | Async ingest and embedding dispatch |
| Vector DB | Qdrant | Hybrid vector retrieval |
| Object storage | MinIO locally, CESNET S3 in production | Evidence and document artifacts |

## Local Quick Start

Prerequisites:

- Docker Compose v2 or Podman Compose
- Git
- Credentials for the configured LLM/VLM endpoint

```bash
cp .env.example .env
# Fill in POSTGRES_*, RABBITMQ_*, JWT_SECRET, FIRST_ADMIN_*, QUERY_*, VLM_*, S3_*.

docker compose up --build
```

Open <http://localhost:8080> and sign in with `FIRST_ADMIN_EMAIL` / `FIRST_ADMIN_PASSWORD`.

Useful local URLs:

| Service | URL |
|---------|-----|
| Frontend | <http://localhost:8080> |
| User documentation | <http://localhost:8080/user-docs/> (public, no login required) |
| API | <http://localhost:8000> |
| Swagger UI | <http://localhost:8000/docs> when `API_DOCS=true` |
| Qdrant dashboard | <http://localhost:6333/dashboard> |
| RabbitMQ management | <http://localhost:15672> |

Example scripts live in `example/`:

```bash
./example/00_set_vars.sh
./example/03_list_sources.sh
./example/04_query.sh "What is Terraform?"
```

## Production

Production runs on Kubernetes through the sibling `infra` repository:

- Frontend and API are exposed at <https://webrag.nss.jkzl.eu>.
- Public script-friendly API paths are available under `/api/*`.
- Secrets are injected from Vault through External Secrets Operator.
- Postgres is managed by CloudNativePG, RabbitMQ by the RabbitMQ operator, and Qdrant by Helm.
- Application images are built by GitHub Actions and promoted in `infra/argocd/apps/webrag/config/kustomization.yaml`.

## Roles

| Area | webrag_admin | webrag_curator | webrag_analyst | webrag_user |
|------|--------------|----------------|----------------|-------------|
| Query | yes | yes | yes | yes |
| REST API Access | yes | yes | yes | yes |
| Knowledge Base | yes | yes | yes | no |
| Sources, Pipeline, Incidents | yes | yes | no | no |
| Experiments | yes | no | yes | no |
| Grafana Dashboard | yes | yes | yes | no |
| Audit Logs and Access Control | yes | no | no | no |

## Key Configuration

All runtime configuration is environment-driven. See `.env.example` for the complete template.

| Variable group | Purpose |
|----------------|---------|
| `POSTGRES_*` | Database connection |
| `RABBITMQ_*` / `RABBITMQ_URL` | Queue connection |
| `S3_*` | Evidence and document object storage |
| `QUERY_*` | Text LLM endpoint and model |
| `VLM_*` | Vision model endpoint and model |
| `JWT_SECRET`, `FIRST_ADMIN_*` | Auth bootstrap |
| `KEYCLOAK_*` | Optional production OIDC |
| `API_DOCS` | Enable `/docs` and `/redoc` locally |

## Documentation

- [REST API reference](docs/api/README.md)
- [Local development and operations](docs/development/README.md)
- [Backend architecture](docs/backend/README.md)
- [Frontend architecture](docs/frontend/README.md)
- [Tests](docs/tests/README.md)
- [CI/CD](docs/.github/README.md)

## Testing

```bash
cd backend
poetry install
poetry run pytest ../tests -v
```

Frontend:

```bash
cd frontend
npm install
npm run build
```

## Repository Layout

```text
app/
├── backend/          # FastAPI API and workers
├── frontend/         # Vue 3 SPA
├── tests/            # Pytest integration/unit tests
├── example/          # Helper scripts for local API workflows
├── docs/             # Detailed docs
├── docker-compose.yml
└── .env.example
```
