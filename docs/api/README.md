# REST API Reference

All endpoints except `GET /health` require bearer authentication:

```http
Authorization: Bearer <token>
```

Tokens can be JWTs from `/auth/login` or opaque personal API tokens generated from the **REST API Access** page.

## Roles

Roles are ordered from highest to lowest privilege:

```text
webrag_admin > webrag_curator > webrag_analyst > webrag_user
```

## Authentication

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/auth/providers` | Public provider discovery for the login page |
| `POST` | `/auth/login` | OAuth2 form login with username and password |
| `POST` | `/auth/local-login` | Password-only bootstrap admin login for the UI |
| `GET` | `/auth/me` | Current authenticated user |
| `POST` | `/auth/refresh` | Reissue JWT with the current DB role |
| `GET` | `/auth/stats` | System counters for the UI |
| `GET` | `/auth/keycloak` | Redirect to Keycloak OIDC |
| `GET` | `/auth/keycloak/callback` | OIDC callback; redirects to frontend with a JWT |
| `GET` | `/auth/api-token/status` | API token status without revealing the token |
| `POST` | `/auth/api-token` | Generate or regenerate a personal opaque API token |

API tokens are shown exactly once. The backend stores only a hash and returns `401` with `{"detail": "API token expired"}` when an expired token is used.

## Sources

| Method | Path | Roles | Purpose |
|--------|------|-------|---------|
| `GET` | `/sources/` | authenticated | List active sources with document counts |
| `POST` | `/sources/` | admin, curator | Create a monitored URL |
| `PATCH` | `/sources/{source_id}` | admin, curator | Update source settings |
| `DELETE` | `/sources/{source_id}` | admin | Soft-delete a source |
| `POST` | `/sources/{source_id}/ingest` | admin, curator | Queue an immediate ingest |
| `GET` | `/sources/pipeline/stats` | authenticated | Pipeline queue counters |
| `GET` | `/sources/jobs/all` | authenticated | List jobs across all sources |
| `POST` | `/sources/jobs/{job_id}/cancel` | admin, curator | Cancel pending/running job |
| `DELETE` | `/sources/jobs/{job_id}` | admin | Delete finished job record |
| `GET` | `/sources/{source_id}/jobs` | authenticated | Recent jobs for a source |

`preferred_strategy` values:

- `api`: Jina.ai reader plus RSS fallback
- `html`: raw HTTP and BeautifulSoup
- `rendered`: Playwright-rendered DOM
- `screenshot`: screenshot plus VLM extraction

Submitted URLs are SSRF-protected: non-HTTP(S), private, loopback, link-local, and hostnames resolving to private addresses are rejected.

## Query

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/query/models` | Return the configured default model for the selector |
| `POST` | `/query/` | Ask a RAG or no-RAG question |

Example request:

```json
{
  "question": "What are the pricing tiers?",
  "mode": "rag",
  "top_k": 5,
  "source_id": null,
  "strict_grounding": true,
  "upstream_provider": null,
  "upstream_base_url": null,
  "upstream_api_key": null,
  "upstream_model": null
}
```

Supported modes:

- `rag`: retrieve chunks first, then answer with citations.
- `no_rag`: ask the LLM directly without indexed context.
- `keyword_fallback`: response mode used when Qdrant is unavailable and Postgres full-text search is used.

Custom user-supplied providers are intentionally limited to OpenAI and OpenRouter. Provider base URLs are host-validated to avoid SSRF.

## Documents

| Method | Path | Roles | Purpose |
|--------|------|-------|---------|
| `GET` | `/documents/` | admin, curator, analyst | List documents |
| `GET` | `/documents/stats` | admin, curator, analyst | Knowledge-base counters |
| `GET` | `/documents/{doc_id}` | admin, curator, analyst | Fetch one document |
| `GET` | `/documents/{doc_id}/chunks` | admin, curator, analyst | List document chunks |
| `DELETE` | `/documents/{doc_id}` | admin, curator | Delete document, chunks, and vectors |
| `GET` | `/documents/{doc_id}/markdown` | admin, curator, analyst | Download markdown |
| `GET` | `/documents/evidence/{evidence_id}/url` | admin, curator, analyst | Pre-signed evidence URL |

Document deletion also removes matching Qdrant vectors.

## Incidents

| Method | Path | Roles | Purpose |
|--------|------|-------|---------|
| `GET` | `/incidents/` | admin, curator | List CAPTCHA/block incidents |
| `POST` | `/incidents/{incident_id}/resolve` | admin, curator | Resolve an incident |
| `POST` | `/incidents/simulate` | admin | Create a synthetic CAPTCHA incident |

Incidents are created automatically when ingest detects CAPTCHA, rate-limit, or block pages.

## Experiments

Experiment models and services are present, but the running API currently exposes only scaffolded experiment behavior. See `routers/experiments.py` and `services/experiment.py` before relying on this surface.

## Health and Metrics

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `GET` | `/health` | no | Liveness/readiness probe |
| `GET` | `/metrics` | no | Prometheus metrics |

Primary metrics include ingest counters/durations, query counters/latency, embedded chunk counters, CAPTCHA incidents, active sources, open incidents, and Qdrant collection size.

## Curl Examples

```bash
TOKEN="<WEBRAG_API_TOKEN>"
API="http://localhost:8080"

curl -s "$API/health"

curl -s "$API/auth/me" \
  -H "Authorization: Bearer $TOKEN"

curl -s "$API/sources/?limit=25" \
  -H "Authorization: Bearer $TOKEN"

curl -s -X POST "$API/query/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question":"What sources are indexed?","mode":"rag","top_k":5,"strict_grounding":true}'
```

Production clients can use `https://webrag.nss.jkzl.eu/api/...`; Traefik rewrites `/api/*` before forwarding to the backend.
