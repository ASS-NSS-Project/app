# Frontend Documentation

Vue 3 + TypeScript single-page application (SPA) served via nginx.

---

## Directory Structure

```text
frontend/
├── src/
│   ├── main.ts             # App entry point + Keycloak token handler (?token= param) + Vue global error handler
│   ├── App.vue             # Root component (auth expiry listener)
│   ├── router/
│   │   └── index.ts        # Vue Router: hash-based routing
│   ├── stores/
│   │   ├── auth.ts         # Pinia: JWT storage, isAuthenticated(), user info
│   │   └── query.ts        # Pinia: query history
│   ├── api/
│   │   ├── client.ts       # Native fetch API client with structured error logging
│   │   └── types.ts        # TypeScript types for all API responses
│   ├── views/              # 7 page components (see below)
│   ├── components/         # Shared: AppLayout, AppSidebar, StatusBadge
│   ├── assets/
│   │   ├── main.css        # Global styles
│   │   └── keycloak-logo.png
│   └── utils/
│       └── time.ts         # Date formatting utilities
├── nginx.conf              # Static file server: SPA fallback (try_files → index.html), security headers
├── Dockerfile              # node:20 build → nginx:alpine serve
├── vite.config.ts          # Dev proxy: /auth, /sources, /query, … → http://localhost:8000
├── tailwind.config.js      # Tailwind CSS configuration
├── postcss.config.js       # PostCSS configuration
├── index.html              # SPA entry point
├── package.json            # npm dependencies
└── package-lock.json       # Locked dependency tree
```

---

## Views (Pages)

The application has **8 views**. All routes except `/login` require authentication.

| View | Route | Description | Accessible by roles |
|------|-------|-------------|---------------------|
| **LoginView** | `/login` | Login page (password-only for admin, "Sign in with OIDC" button if Keycloak configured) | Public |
| **QueryView** | `/query` | RAG query interface — ask questions, select model, view answers with citations | All authenticated users |
| **ApiTokenView** | `/api-token` | Generate or regenerate a personal opaque API token for programmatic access | All authenticated users |
| **SourcesView** | `/sources` | Manage sources (add, edit, delete, trigger ingest) | webrag_admin, webrag_curator |
| **PipelineView** | `/pipeline` | View ingest job history across all sources, see fallback chain status per job | webrag_admin, webrag_curator |
| **IncidentsView** | `/incidents` | CAPTCHA incident management (view, resolve, simulate) | webrag_admin, webrag_curator |
| **KnowledgeBaseView** | `/knowledge-base` | Browse indexed documents, filter by source, view chunks, download markdown | webrag_admin, webrag_curator, webrag_analyst |
| **ExperimentsView** | `/experiments` | Run batch query experiments, view metrics (recall@k, MRR, nDCG) | webrag_admin, webrag_analyst |

**External links** (opened in new tab, not SPA routes):

- **Dashboard** → `https://grafana.nss.jkzl.eu/d/webrag-overview` (Grafana dashboard)
- **Audit Logs** → `https://grafana.nss.jkzl.eu/d/webrag-audit` (Grafana logs panel)
- **Users** → `https://keycloak.nss.jkzl.eu` (Keycloak admin console, webrag_admin only)

The router enforces roles client-side and redirects to `/query` if the role is insufficient. `/query` is the default landing page for all authenticated users.

---

## Components

| Component | Purpose |
|-----------|---------|
| **AppLayout** | Main layout wrapper with sidebar navigation |
| **AppSidebar** | Sidebar with navigation links — visibility controlled by user role |
| **StatusBadge** | Color-coded status badge (pending/running/done/failed/captcha_blocked) |

---

## API Client

**File:** `src/api/client.ts`

Uses native **fetch API** (not Axios). All requests include the JWT token from the auth store in the `Authorization` header. Structured error logging via `logError()` — writes JSON to `console.error` with `event` slug (`api_error`, `network_error`).

**Error handling:**

- HTTP errors (4xx, 5xx) log `event: api_error` with status, method, URL
- Network errors (no response) log `event: network_error`
- All errors are caught by the Vue global error handler in `main.ts` which logs `event: vue_error`
- Unhandled promise rejections log `event: unhandled_promise_rejection`

Frontend errors appear in the `webrag-frontend` pod's stdout in production and are collected by Alloy → Loki.

---

## Authentication Flow

### Password-only login (admin account)

1. User enters password in LoginView
2. `POST /auth/local-login` with `{password}`
3. Backend returns JWT + user info
4. Token stored in Pinia auth store + localStorage
5. Redirect to `/query`

### Keycloak OIDC login

1. User clicks "Sign in with OIDC" button (shown only when `GET /auth/providers` returns `{keycloak: true}`)
2. Browser redirects to `GET /auth/keycloak` → Keycloak login page
3. User authenticates via Google identity broker
4. Keycloak redirects to `/auth/keycloak/callback`
5. Backend issues JWT and redirects to frontend with `?token=<jwt>` query param
6. Frontend's OAuth callback handler in `main.ts` reads `?token=`, stores it, redirects to `/query`

### Token expiry

The `App.vue` root component listens for JWT expiry. When the token expires, the user is redirected to `/login` and the token is cleared from localStorage.

### Role refresh

If the user's Keycloak role changes (e.g. promoted from `webrag_user` to `webrag_curator`), the frontend can call `POST /auth/refresh` to get a new JWT with the updated role without requiring a full re-login.

---

## Styling

- **Tailwind CSS** for utility classes
- **PostCSS** for processing
- **Global styles** in `src/assets/main.css`

---

## Development

### Local dev server

```bash
cd frontend
npm install
npm run dev
```

The dev server runs on `http://localhost:5173` with Vite HMR. API requests are proxied to `http://localhost:8000` via `vite.config.ts`.

### Build for production

```bash
npm run build
```

Outputs static files to `dist/`. The Dockerfile copies these into an nginx:alpine container.

---

## nginx Configuration

**File:** `nginx.conf`

- **SPA fallback:** `try_files $uri $uri/ /index.html` — all unknown routes serve `index.html` for client-side routing
- **Security headers:** `X-Frame-Options`, `X-Content-Type-Options`, `X-XSS-Protection`, `Referrer-Policy`
- **API proxy (production only):** `/api/*` → `http://webrag-api:8000/*` (path rewrite) — disabled in Docker Compose (nginx doesn't resolve `webrag-api` hostname at startup)

In Kubernetes, the frontend nginx uses a ConfigMap (`webrag-frontend-nginx`). In Docker Compose, proxy_pass blocks are stripped to avoid startup crashes.

---

## Document Title

The HTML document title is **WebRAG** (browser tab title).

---

## TypeScript Types

**File:** `src/api/types.ts`

Contains TypeScript interfaces for all API responses: `UserResponse`, `SourceResponse`, `JobResponse`, `QueryResponse`, `DocumentResponse`, `ChunkResponse`, `IncidentResponse`, `ExperimentResponse`, etc.

These types are derived from the FastAPI Pydantic schemas and should be kept in sync when the backend API changes.

---

## UI Behavior Notes

### Query View

- The autosizing textarea resets to compact height when cleared (including whitespace-only content)
- Model selector is populated from `GET /query/models` — backend exposes only configured providers
- Citations are displayed below the answer with relevance scores
- `mode` toggle: `rag` (default) retrieves chunks first; `no_rag` asks the LLM directly

**Resilience indicators:**
- Mode tag shows: **RAG** (blue) | **NO_RAG** (gray) | **KEYWORD SEARCH** (orange)
- When backend falls back to keyword search (Qdrant down or embeddings not ready):
  - Warning banner appears: "Vector search unavailable, using keyword fallback"
  - Mode tag shows "KEYWORD SEARCH" in orange
  - Results are functional but may have lower relevance than vector search

**Response fields:**
- `answer` — LLM-generated answer
- `mode` — `"rag"` | `"no_rag"` | `"keyword_fallback"`
- `citations[]` — Retrieved chunks with URLs and relevance scores
- `chunks_retrieved` — Number of chunks used
- `warning` — Optional message explaining degraded mode

### Pipeline View

- Fallback chain renders as four equal-width cards: API/Feed → HTML → Rendered → Screenshot+VLM
- Step badges use `-`, `PENDING`, `READY`, `FAILED`, `SKIPPED` statuses
- If a later strategy is selected directly (e.g. screenshot), predecessor steps show as `SKIPPED` in blue
- Methods legend is displayed below the chain as a full-width panel

### Knowledge Base View

- Chunks are opened explicitly via the **Chunks** action button in each row (row click does not open chunks)
- Document search box filters by title and URL text
- Source ID filter is a selectable dropdown populated from known sources
- Source IDs are shown in full in the table and the selector

### Sources View

- `preferred_strategy` options: `api` (Jina.ai reader + RSS fallback), `html`, `rendered`, `screenshot`
- The `api` strategy fetches `https://r.jina.ai/{url}`, strips Jina metadata preamble, chunks the markdown using VLM block chunker
- URLs pointing to private/loopback addresses are rejected by backend (SSRF protection)

### Incidents View

- Filter by status: `open`, `in_progress`, `resolved`
- **Test CAPTCHA detection:** create a source with `base_url: https://www.google.com/recaptcha/api2/demo` and `preferred_strategy: rendered`, trigger ingest → incident appears automatically

---

## Role-Based Navigation Visibility

Navigation items in the sidebar are shown/hidden based on the user's role:

| Section | webrag_admin | webrag_curator | webrag_analyst | webrag_user |
|---------|-----------|-------------|-------------|----------|
| Query (RAG) | ✓ | ✓ | ✓ | ✓ |
| Knowledge Base | ✓ | ✓ | ✓ | — |
| Sources, Pipeline, Incidents | ✓ | ✓ | — | — |
| Experiments | ✓ | — | ✓ | — |
| Dashboard ↗ (Grafana) | ✓ | ✓ | ✓ | — |
| Audit Logs ↗ (Grafana) | ✓ | ✓ | ✓ | — |
| Users ↗ (Keycloak) | ✓ | — | — | — |
