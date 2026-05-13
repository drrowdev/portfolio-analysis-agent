# AGENTS.md — Onboarding for AI Assistants

This file tells AI assistants (Copilot, Claude, etc.) working in this repo **what to read first, what to keep in sync, and what pitfalls to avoid**. Humans are welcome to read it too.

## TL;DR

- Repo: **portfolio-analysis-agent** — FastAPI + React portfolio tracker. Backend deploys to Azure Container Apps; frontend deploys to Azure Static Web Apps (Free tier). Both via GitHub Actions on push to `main`.
- Always run linters/tests before committing.
- Use **conventional commits** (`feat:`, `fix:`, `docs:`, `chore:`, `refactor:`).
- Always include the co-author trailer:
  ```
  Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
  ```
- **Update docs alongside code** per the policy table below — don't rely on a cron job to sync them.

## Doc-Update Policy

When you make a change of a given **kind**, update the docs in the corresponding row **in the same PR/commit**. If you skip a row, justify it in the commit body.

| Change kind | `README.md` | `CHANGELOG.md` | `backend/.env.example` | Alembic migration | Notes |
|---|---|---|---|---|---|
| New API endpoint / router | ✅ add to endpoint table | ✅ `Added` | — | — | Update the route table near "API Endpoints". |
| Removed / renamed endpoint | ✅ update table | ✅ `Changed`/`Removed` | — | — | Note breaking changes prominently. |
| New feature (user-visible) | ✅ Features list | ✅ `Added` | — | — | Screenshot if it's UI-heavy. |
| Bug fix | — | ✅ `Fixed` | — | — | One line, link the commit. |
| New dependency (backend) | possibly Tech Stack | ✅ `Changed` | — | — | Pin in `pyproject.toml`. |
| New dependency (frontend) | possibly Tech Stack | ✅ `Changed` | — | — | Pin in `package.json`. |
| New env var | ✅ Env Vars section | ✅ `Changed` | ✅ add with placeholder | — | Document what breaks if it's missing. |
| Removed env var | ✅ remove from list | ✅ `Removed` | ✅ remove | — | — |
| DB schema change | possibly Architecture | ✅ `Changed` | — | ✅ new revision | Run `alembic revision --autogenerate`. |
| New Azure resource | ✅ Azure Resources section | ✅ `Changed` | — | — | Also update `azure-resources.txt`. |
| CI/CD change | — | ✅ `Changed` | — | — | Update `.github/workflows/deploy.yml` carefully. |
| Architecture change (new service, queue, scheduler, etc.) | ✅ Architecture diagram | ✅ `Changed` | — | — | Update `architecture.excalidraw` + re-export `architecture.png`. |
| Trivial refactor / typo / formatting | — | — | — | — | No doc churn needed. |

**Rule of thumb:** if a future contributor (or your future self) would be surprised by your change after only reading the README, the README needs an update.

## Conventional Commits

```
<type>(optional scope): <short summary>

<body — what & why, not how>

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
```

Types in use: `feat`, `fix`, `docs`, `chore`, `refactor`, `perf`, `test`, `ci`, `build`.

## Common Pitfalls

- **Auth** — the app uses a cookie-based password gate (not MSAL). The shared secret is set via `APP_PASSWORD` env var. Don't re-introduce Azure AD dependencies.
- **yfinance rate limits** — cache via `MarketDataCache` model; don't hammer it from request handlers.
- **Anthropic streaming** — use SSE; never buffer the whole response server-side or the chat will feel broken.
- **Alembic autogenerate** is not perfect — review the generated migration before committing. Pay attention to enum changes and index renames.
- **Cross-origin auth cookie** — the `paa_session` cookie is set with `SameSite=None; Secure; HttpOnly` so the SWA-hosted frontend can authenticate against the backend Container App. Always send `credentials: 'include'` on fetch calls (the central `api` module in `frontend/src/lib/api.ts` already does).
- **Frontend → backend URL** — the build-time variable `VITE_API_BASE_URL` controls the API base URL. Set as a GitHub repo Variable for CI; defaults to `/api/v1` for local dev so the Vite proxy keeps working. If the backend URL changes, update both the GH Variable and the `CORS_ORIGINS` env var on the `portfolio-backend` Container App.
- **Container Apps cold start** — backend uses `min_replicas: 0` (scale-to-zero) with a GitHub Actions keep-alive cron (`.github/workflows/keep-alive.yml`) pinging every 4 min. Don't set `min_replicas: 1` — it costs ~€19/month.
- **CSV/PDF importers** — Nordnet/Fidelity formats change yearly. Add a fixture under `backend/tests/fixtures/` whenever you touch a parser.
- **Secrets** — never commit `.env`. `backend/.env` is gitignored; production secrets live in Azure Key Vault.
- **Docker tags** — CI pushes `:latest` and `:<sha>`. Always reference `:<sha>` in Container Apps revisions for traceability.

## Useful Commands

```bash
# Backend
cd backend
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload --port 8000
pytest

# Frontend
cd frontend
npm install
npm run dev
npm run build
npm run lint

# Generate a new Alembic migration
cd backend && alembic revision --autogenerate -m "describe change"
```

## Where Things Live

| You want to... | Look here |
|---|---|
| Add an API route | `backend/app/routers/` |
| Add a DB model | `backend/app/models/` + new Alembic revision |
| Add a Pydantic schema | `backend/app/schemas/` |
| Add a service / business logic | `backend/app/services/` |
| Add a React page | `frontend/src/pages/` |
| Add a React component | `frontend/src/components/` |
| Add a React Query hook | `frontend/src/hooks/` |
| Change deploy pipeline | `.github/workflows/deploy.yml` |
| Document an Azure resource | `azure-resources.txt` + README "Azure Resources" |
