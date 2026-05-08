# Development and Operations

This page contains the local setup, runtime operations, and troubleshooting details that are intentionally kept out of the root README.

## Local Setup

```bash
cp .env.example .env
```

Fill in at least:

- `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`
- `RABBITMQ_DEFAULT_USER`, `RABBITMQ_DEFAULT_PASS`
- `S3_ENDPOINT_URL`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`
- `QUERY_BASE_URL`, `QUERY_API_KEY`, `QUERY_MODEL`
- `VLM_BASE_URL`, `VLM_API_KEY`, `VLM_MODEL`
- `JWT_SECRET`
- `FIRST_ADMIN_EMAIL`, `FIRST_ADMIN_PASSWORD`

Start the stack:

```bash
docker compose up --build
```

For a fresh start:

```bash
docker compose down -v
docker compose up --build
```

## Service URLs

| Service | URL | Notes |
|---------|-----|-------|
| Main UI | <http://localhost:8080> | Frontend nginx |
| API direct | <http://localhost:8000> | FastAPI |
| Swagger UI | <http://localhost:8000/docs> | Requires `API_DOCS=true` |
| ReDoc | <http://localhost:8000/redoc> | Requires `API_DOCS=true` |
| Qdrant dashboard | <http://localhost:6333/dashboard> | Local vector DB |
| RabbitMQ management | <http://localhost:15672> | Queue UI |
| MinIO console | <http://localhost:9001> | Local S3 |

## Object Storage

Local Compose uses MinIO and creates these buckets automatically:

| Bucket | Purpose |
|--------|---------|
| `rag-evidence-dev` | Screenshots and HTML evidence |
| `rag-documents-dev` | Extracted markdown and chunks JSON |

Production uses CESNET S3 buckets provisioned by `infra/terraform/du-cesnet` and credentials from Vault through ESO.

The browser never receives S3 credentials. Evidence and markdown downloads use API-generated pre-signed URLs.

## Embedding Model

The system uses `BAAI/bge-m3` through FlagEmbedding:

| Property | Value |
|----------|-------|
| Download size | about 570 MB |
| RAM loaded | about 2.3 GB with fp16 |
| Used by | API query embedding and embedding worker |

The first startup downloads weights from Hugging Face Hub. Later starts use the Hugging Face cache volume. `HF_HUB_DISABLE_PROGRESS_BARS=1` must stay enabled so structured logs are not polluted by progress bars.

## Logs

All backend services emit structured JSON logs. Important fields include `timestamp`, `level`, `logger`, `service`, `event`, and `message`.

```bash
docker compose logs -f api
docker compose logs -f worker_ingest
docker compose logs -f worker_embed
docker compose logs -f frontend
```

Filter by event:

```bash
docker compose logs api | grep '"event": "query_failed"'
docker compose logs worker_ingest | grep '"event": "ingest_completed"'
docker compose logs worker_embed | grep '"event": "embedding_failed"'
```

Common event groups:

| Event group | Examples |
|-------------|----------|
| HTTP | `http_request`, `http_error` |
| Query | `query_received`, `query_completed`, `query_failed`, `search_failed` |
| Ingest | `ingest_started`, `ingest_completed`, `ingest_failed`, `captcha_detected` |
| Embedding | `embedding_started`, `embedding_job_completed`, `embedding_job_failed` |
| Auth | `login_success`, `login_failed`, `jwt_invalid`, `api_token_generated` |
| Frontend | `api_error`, `network_error`, `vue_error`, `unhandled_promise_rejection` |

## API Docs

Interactive docs are disabled by default.

```bash
API_DOCS=true
docker compose restart api
```

Then open:

- <http://localhost:8000/docs>
- <http://localhost:8000/redoc>

## Backend Development

```bash
cd backend
poetry install
poetry run pytest ../tests -v
```

Dependencies are managed by Poetry. If dependencies change, commit both `pyproject.toml` and the lock file.

## Frontend Development

```bash
cd frontend
npm install
npm run dev
npm run build
```

The Vite dev server proxies API paths to `http://localhost:8000`.

## Production Notes

Production runs from the `infra` repository. The API image is reused for:

- API Deployment: `uvicorn main:app`
- Ingest worker StatefulSet: `python worker_ingest.py`
- Embedding worker StatefulSet: `python worker_embed.py`

The public production API uses the `/api` prefix:

```bash
curl -s https://webrag.nss.jkzl.eu/api/health
```

Worker StatefulSets use per-replica Hugging Face cache PVCs because the BGE-M3 cache is `ReadWriteOnce`.

## Troubleshooting

**API or worker is slow to start**

BGE-M3 is loading into memory. Watch for `model_load_start` and `model_load_complete`.

**API waits for Postgres or RabbitMQ**

First boot can take 30-60 seconds. The containers poll TCP ports before starting app processes.

**Worker is not processing jobs**

Check `worker_ingest` and `worker_embed` logs. Rebuild if import errors appear.

**Vision extraction fails**

Verify `VLM_BASE_URL`, `VLM_API_KEY`, and `VLM_MODEL`.

**S3 upload errors**

Verify S3 endpoint, credentials, bucket names, and MinIO initialization status.

**Playwright screenshot errors**

Rebuild the worker image if Chromium dependencies are stale:

```bash
docker compose build --no-cache worker_ingest
```

**Podman RabbitMQ cookie errors**

The compose entrypoint pre-writes the Erlang cookie for rootless Podman. If old volume permissions are broken, recreate volumes with `podman compose down -v`.
