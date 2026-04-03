# CI/CD & Pre-commit — Changes from ASS-NSS-Project/repo

---

## Pre-commit (`.pre-commit-config.yaml`)

**Identical to the reference repo.**  Uses
[`conventional-pre-commit`](https://github.com/compilerla/conventional-pre-commit)
at `v4.4.0` to enforce [Conventional Commits](https://www.conventionalcommits.org/)
on the `commit-msg` hook stage.

Install locally:

```bash
pip install pre-commit
pre-commit install --hook-type commit-msg
```

After installation every commit message is validated automatically.

---

## GitHub Actions (`.github/workflows/ci.yml`)

The reference repo has a single `commit-msg-check.yml` workflow that uses
Poetry.  This project replaces it with a single **`ci.yml`** that runs three
jobs in parallel:

### 1. `commit-message-check`

Same intent as the reference repo's workflow.  Runs `pre-commit` without
Poetry (plain `pip install pre-commit`) and checks the latest commit message.

### 2. `backend-tests`

Runs the pytest suite in `tests/` against a real PostgreSQL service container
(port 5432) and Redis (port 6379, used by RQ worker).

- Python 3.11
- `pip install -r backend/requirements.txt pytest pytest-asyncio httpx`
- Environment variables set to point at the service containers

> **Note:** Qdrant, RabbitMQ, MinIO, and Ollama are **not** started in CI
> because they are either too heavy for free runners or require GPU.
> Tests that would hit those services should be skipped with
> `pytest.mark.skipif` until a self-hosted runner is available.

### 3. `frontend-build`

Runs `npm install && npm run build` (type-check + Vite build) to catch
TypeScript errors and import issues before merge.

- Node.js 20
- `npm` cache keyed on `frontend/package-lock.json`

---

## Why not Poetry?

The reference repo uses Poetry.  This project uses `pip + requirements.txt`
in the CI backend job to stay consistent with the Docker build.  If the
project migrates to Poetry in the future, replace the `pip install` step with
`poetry install` and adjust `working-directory` accordingly.
