# Portfolio Analysis Agent

AI-powered investment portfolio tracker and analyzer for Finnish tax-aware accounts.

📖 See [`CHANGELOG.md`](CHANGELOG.md) for release history and [`AGENTS.md`](AGENTS.md) for the doc-update policy that keeps this README in sync with the code.

## Features

- **Real-time portfolio tracking** — Live prices via yfinance with automatic refresh; holdings shown in each stock's native listed currency (USD, EUR, …)
- **AI-powered analysis** — Daily summaries, rebalance recommendations, tax optimization (Claude Sonnet 5)
- **Streaming AI chat** — Ask questions about your portfolio in natural language
- **Multi-broker import** — Nordnet (CSV) and Fidelity ESPP (PDF), with USD→EUR converted on import at each trade's historical ECB rate
- **Manual trade entry & editing** — Record, edit, or delete trades with per-field EUR/USD currency toggles and trade-date FX rates
- **Finnish capital-gains tax suite** — Per-sale ennakkovero calculator (per-lot hankintameno-olettama, 30 %/34 % bracket), year-to-date €30k capital-income tracker, and OmaVero declaration & payment tracking with PDF export
- **Finnish tax-aware accounts** — Arvo-osuustili, OST, ESPP, and Crypto account types
- **Market news & alerts** — Price, earnings, rebalance, and news-triggered alerts
- **Investment goals** — Track progress toward financial targets
- **Mobile-responsive UI** — Works on desktop and mobile (Bearer-token auth fallback for browsers that block cross-site cookies)

## Tech Stack

| Layer | Stack |
|-------|-------|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0, PostgreSQL |
| Frontend | React 19, TypeScript, Vite, Tailwind CSS, Recharts |
| Auth | Shared-password gate — HTTP-only `paa_session` cookie (`SameSite=None; Secure`) with `Authorization: Bearer` fallback for mobile |
| AI | Anthropic Claude Sonnet 5 (streaming chat + scheduled analysis) |
| Market Data | yfinance, Finnhub, NewsAPI, Frankfurter (ECB FX) |
| Deployment | Backend: Docker + Azure Container Apps. Frontend: Azure Static Web Apps (Free tier). GitHub Actions CI/CD. |

## Architecture

```
┌──────────────────┐                  ┌──────────────────┐
│  React SPA       │  cross-origin    │   FastAPI        │
│  Azure Static    │ ───── HTTPS ───▶ │  Azure Container │
│  Web Apps (Free) │  (cookie auth)   │  Apps (Uvicorn)  │
└──────────────────┘                  └────────┬─────────┘
                                               │
                          ┌─────────────┬──────┼──────────────┐
                          │             │      │              │
                     ┌────▼───┐   ┌─────▼──┐   │   ┌──────────▼──┐
                     │ Claude │   │yfinance│   │   │  Scheduler  │
                     │  API   │   │ + News │   │   │(APScheduler)│
                     └────────┘   └────────┘   │   └─────────────┘
                                               │
                                        ┌──────▼──────┐
                                        │ PostgreSQL  │
                                        │  (Azure)    │
                                        └─────────────┘
```

## API Endpoints

| Route | Description |
|-------|-------------|
| `/api/v1/auth` | Login + auth check for the shared-password gate |
| `/api/v1/dashboard` | Combined above-the-fold dashboard payload (single request) |
| `/api/v1/accounts` | Account management (CRUD) |
| `/api/v1/holdings` | Holdings with live prices (native currency), quick trades |
| `/api/v1/portfolio` | Portfolio summary, performance, allocation |
| `/api/v1/transactions` | Transaction history, edit/delete, capital-income summary |
| `/api/v1/transactions/tax-calculations` | Saved ennakkovero calcs: CRUD, OmaVero declaration tracking, PDF export |
| `/api/v1/analysis` | AI insights: daily summary, rebalance, tax optimization, news impact |
| `/api/v1/chat` | Streaming AI chat grounded in portfolio context |
| `/api/v1/strategies` | Investment strategy and target allocation |
| `/api/v1/goals` | Investment goals tracking |
| `/api/v1/alerts` | Alert management (price, news, earnings, rebalance) |
| `/api/v1/news` | Market news with impact analysis |
| `/api/v1/settings` | User settings; `/api/v1/fx/eurusd` for historical EUR/USD rates |
| `/api/v1/market-status` | US / Helsinki market open-closed state + next open |
| `/api/v1/upload` | CSV/PDF file import |

## Local Development

### Prerequisites

- Python 3.12+
- Node.js 20+
- Docker (optional, for containerized runs)

### Backend

```bash
cd backend
cp .env.example .env  # Configure API keys and DB
pip install -e .
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev  # Starts on http://localhost:5173
```

### Environment Variables

Backend (`.env`, see `backend/.env.example`):
- `DATABASE_URL` — PostgreSQL connection string (or omit for SQLite in local dev)
- `ANTHROPIC_API_KEY` — Claude API key for AI features
- `APP_SECRET` — shared password for the cookie/Bearer access gate (leave empty to disable the gate locally)
- `FINNHUB_API_KEY` — Market news (optional)
- `NEWS_API_KEY` — News aggregation (optional)
- `NTFY_TOPIC` — ntfy.sh topic for push alerts (optional; default `portfolio-alerts`)
- `CORS_ORIGINS` — comma-separated allowed frontend origins (production only; set on the Container App)

Frontend (build-time):
- `VITE_API_BASE_URL` — backend API base URL baked in at build; defaults to `/api/v1` for local dev (Vite proxy)

## Deployment

Deployed automatically via GitHub Actions on push to `main`:

1. **Backend** — Docker image built and pushed to Azure Container Registry, then deployed to an Azure Container App.
2. **Frontend** — Vite builds `frontend/dist/` with `VITE_API_BASE_URL` baked in (from the `VITE_API_BASE_URL` repo Variable), then deployed to Azure Static Web Apps via `azure/static-web-apps-deploy@v1` using the `AZURE_STATIC_WEB_APPS_API_TOKEN` secret.

The frontend calls the backend cross-origin. CORS is configured via the `CORS_ORIGINS` env var on the backend Container App, and the auth cookie uses `SameSite=None; Secure` for cross-origin sessions.

### Azure Resources

- **Resource Group** with a `CanNotDelete` lock
- **Container App** running the FastAPI/Uvicorn backend
- **Static Web App** (Free tier) hosting the React frontend
- **Azure PostgreSQL Flexible Server** for portfolio data
- **Azure Container Registry** for backend images
- **Azure Key Vault** for secrets

## Project Structure

```
portfolio-analysis-agent/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app entry point
│   │   ├── routers/             # API route handlers
│   │   ├── models/              # SQLAlchemy models
│   │   ├── services/            # Business logic (market data, AI, alerts)
│   │   ├── routers/gate.py      # Shared-password auth gate (cookie + Bearer)
│   │   └── config.py            # Configuration
│   ├── alembic/                 # Database migrations
│   ├── tests/                   # Backend tests
│   ├── Dockerfile
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── pages/               # Route pages
│   │   ├── components/          # React components
│   │   ├── hooks/               # Custom hooks (React Query)
│   │   └── types/               # TypeScript types
│   └── package.json             # Built by Vite → deployed to Azure Static Web Apps
└── .github/workflows/deploy.yml # CI/CD pipeline
```
