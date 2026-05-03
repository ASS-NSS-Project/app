# CI/CD

GitHub Actions workflow for testing, building, and publishing container images.

---

## Triggers

| Event | Branches/Tags | Jobs Run |
|-------|--------------|----------|
| Pull request | any | conventional-commits, backend-tests, frontend-build |
| Push | `main`, `kost` | All jobs + build-and-push |
| Tag | `v*.*.*` | All jobs + build-and-push |

---

## Jobs

### Conventional commits

Enforces [Conventional Commits](https://www.conventionalcommits.org/) on every commit message. Uses `conventional-pre-commit` via `pre-commit` — config in `.github/config/pre-commit-config.yaml`.

**Allowed types:** `feat`, `fix`, `chore`, `docs`, `refactor`, `test`, `ci`, `build`, and others from the conventional commits spec.

**Implementation:** Extracts commit message from the most recent commit (or PR head for pull requests) and runs `pre-commit run --hook-stage commit-msg` to validate format.

---

### Backend tests

Runs the pytest suite against a real PostgreSQL 16 database (GitHub Actions service container).

**Environment:**
- Python 3.11
- PostgreSQL 16 (service container on port 5432)
- Poetry for dependency management

**Steps:**
1. Install Poetry + `poetry-plugin-export`
2. Export main dependencies to `requirements.txt` (without hashes, main group only)
3. Install lightweight test dependencies: exported requirements + pytest + pytest-asyncio + httpx
4. Run tests: `pytest tests/test_api.py tests/test_config.py -q`

**Environment variables:**
- `PYTHONPATH=${{ github.workspace }}/backend`
- `POSTGRES_*` — connection to service container
- `JWT_SECRET` — CI-specific test secret
- `FIRST_ADMIN_*` — bootstrap admin credentials
- `FRONTEND_URL=http://localhost:5173`

**Note:** BGE-M3 embedding model is NOT loaded in CI (too slow/memory-intensive). RAG query tests with real embeddings are skipped.

---

### Frontend build

Verifies that the frontend builds successfully and TypeScript types are valid.

**Environment:**
- Node.js 22
- npm for dependency management
- Working directory: `frontend/`

**Steps:**
1. Set up Node.js with npm cache (caches `frontend/package-lock.json`)
2. Install dependencies: `npm install`
3. Type-check and build: `npm run build` (runs Vite build + TypeScript check)

---

### Build and push

Builds Docker images for `rag-api` (backend) and `rag-frontend` and pushes them to GitHub Container Registry (`ghcr.io/ass-nss-project/`).

**Conditions:**
- **Only runs on push events** (not PRs)
- **Only runs after** `backend-tests` and `frontend-build` pass
- **Only runs for:** `main`, `kost` branches, or semver tags (`v*.*.*`)

**Images:**
- `ghcr.io/ass-nss-project/rag-api` — FastAPI backend (also used for worker with different command)
- `ghcr.io/ass-nss-project/rag-frontend` — Vue 3 + nginx SPA

**Tag strategy:**

| Trigger | Tags Produced |
|---------|---------------|
| Push to `main` | `main-<short-sha>` |
| Push to `kost` | `kost-<short-sha>` |
| Git tag `v1.2.3` | `1.2.3`, `1.2` |

**Features:**
- Docker Buildx for multi-platform builds
- GitHub Actions cache for layer caching (`type=gha`)
- Automatic login to GHCR using `GITHUB_TOKEN`

**Permissions required:**
- `contents: read` — checkout code
- `packages: write` — push to GHCR

---

## Config Files

| File | Used by |
|------|---------|
| `.github/config/pre-commit-config.yaml` | Conventional commits job |

---

## Testing Locally

### Run backend tests

```bash
cd backend
poetry install
poetry run pytest ../tests/ -v
```

### Run frontend build

```bash
cd frontend
npm install
npm run build
```

### Build Docker images locally

```bash
# API image
docker build -t rag-api:local ./backend

# Frontend image
docker build -t rag-frontend:local ./frontend
```

---

## CI Status Badge

Check the workflow status on the [Actions tab](../../actions) or add a badge to README.md:

```markdown
![CI](https://github.com/ASS-NSS-Project/app/actions/workflows/ci.yml/badge.svg?branch=kost)
```

---

## Troubleshooting

**Backend tests fail with "connection refused":**
- Check that the Postgres service container started successfully
- Verify `POSTGRES_HOST=localhost` (not `127.0.0.1` or `postgres`)

**Frontend build fails with "out of memory":**
- Node.js 22 is used — verify `package-lock.json` is compatible
- Check for memory-intensive PostCSS/Tailwind plugins

**Build-and-push skipped on push:**
- Check that both `backend-tests` and `frontend-build` passed first
- Verify branch name is exactly `main` or `kost` (case-sensitive)
- For tags, verify format is `v*.*.*` (semver with `v` prefix)

**Images not appearing in GHCR:**
- Check that `GITHUB_TOKEN` has `packages: write` permission
- Verify the organization/user has GHCR enabled
- Check for rate limits or authentication errors in logs
