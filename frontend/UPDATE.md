# Frontend — Changes from ASS-NSS-Project/repo

This document describes every divergence from the reference repo so that
contributors familiar with that codebase can orient themselves quickly.

---

## What was adopted unchanged

| Item | Source |
|------|--------|
| `tailwind.config.js` | copied verbatim |
| `postcss.config.js` | copied verbatim |
| `tsconfig.json` (references style) | copied verbatim |
| `tsconfig.app.json` (extends `@vue/tsconfig`) | copied verbatim |
| `vite.config.ts` (fileURLToPath alias) | copied, proxy section kept |
| `src/vite-env.d.ts` | copied verbatim |
| `src/main.ts` PrimeVue + Aura registration | copied |
| Package versions (Vue 3.5, Pinia 3, PrimeVue 4.5, Vite 7, TS 5.9…) | matched |

---

## What was extended / kept from the original project

### `package.json`
- `axios` **removed** — replaced by native `fetch` (matches repo intent).
- All version numbers bumped to match the reference repo.
- `name` stays `rag-frontend` (not `frontend`) to avoid Docker image naming conflicts.

### `vite.config.ts`
- Dev-server **proxy** block kept as-is (`/auth`, `/sources`, `/query`,
  `/incidents`, `/health` → `http://localhost:8000`).  The reference repo
  uses a single `/api` prefix; we keep the original per-path proxies because
  the backend routers are mounted without a common prefix.

### `src/assets/main.css`
- **Tailwind v4 import** added at the top with correct CSS layer ordering
  (`tailwind-base → primevue → tailwind-utilities`) so PrimeVue styles can
  be overridden by Tailwind utilities when needed.
- Original **CSS custom properties** (`--bg`, `--surface`, `--accent`, …)
  and all hand-written component styles are preserved so the dark theme
  continues to work for non-PrimeVue elements.
- PrimeVue DataTable dark-mode overrides added at the bottom to match the
  existing dark palette.

### `index.html`
- `class="app-dark"` added to `<html>` — activates PrimeVue Aura dark mode
  (selector configured as `.app-dark` in `main.ts`).
- Google Fonts `<link>` for Inter kept.

### `src/main.ts`
- Google OAuth token bootstrap logic kept (runs before router guard).
- PrimeVue registered with Aura theme, `darkModeSelector: '.app-dark'`.

### `src/api/client.ts`
- **Rewrote from axios to native `fetch`** while keeping the identical
  exported API (`get`, `post`, `patch`, `del`, `loginForm`).
- Error objects are shaped identically (`err.response.data.detail`) so
  all existing catch blocks in the views work without modification.
- `loginForm` still sends `application/x-www-form-urlencoded` as required
  by FastAPI's `OAuth2PasswordRequestForm`.

### Vue components
All existing components were migrated to **PrimeVue v4** interactive
elements while keeping the original business logic, TypeScript types, and
routing untouched.

| Component | PrimeVue components used |
|-----------|--------------------------|
| `StatusBadge.vue` | `Tag` (severity mapped from status string) |
| `AppLayout.vue` | `Button` (sign-out) |
| `LoginView.vue` | `InputText`, `Password`, `Button`, `Message`, `Divider` |
| `DashboardView.vue` | `DataTable`, `Column`, `Tag` |
| `SourcesView.vue` | `DataTable`, `Column`, `Dialog`, `Button`, `InputText`, `InputNumber`, `Select`, `Tag`, `Message` |
| `QueryView.vue` | `Textarea`, `Select`, `InputNumber`, `Checkbox`, `Button`, `Tag` |
| `IncidentsView.vue` | `DataTable`, `Column`, `Dialog`, `Button`, `Textarea`, `Tag` |
| `AuditView.vue` | `DataTable`, `Column`, `Tag` |
| `UsersView.vue` | `DataTable`, `Column`, `Select`, `Button`, `Tag` |

`AppSidebar.vue` was not changed — `router-link` navigation with PrimeIcons
available via the global CSS import is sufficient.

---

## Deployment — no changes needed

Docker Compose, Nginx config, Dockerfiles, and `.env` are **unchanged**.
The frontend container still runs `npm run build` and serves the `dist/`
folder via Nginx. No new environment variables are required.

---

## Running locally after the upgrade

```bash
cd frontend
npm install          # pulls new deps (PrimeVue, Tailwind, etc.)
npm run dev          # Vite dev server with proxied backend
npm run build        # production build (type-check + Vite)
```
