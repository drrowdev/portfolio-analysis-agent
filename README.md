# Portfolio Analysis Agent

Investment portfolio cockpit for Finnish tax-aware accounts.

📖 See [`CHANGELOG.md`](CHANGELOG.md) for release history and [`AGENTS.md`](AGENTS.md) for the doc-update policy that keeps this README in sync with the code.

## Features

- **Real-time portfolio tracking** — Live prices via yfinance with automatic refresh; holdings shown in each stock's native listed currency (USD, EUR, …)
- **Portfolio cockpit** — Refresh prices, risk limits, benchmark facts, turnover, and tracked Finnish tax estimates; the default stance is no action unless reliable evidence supports review
- **News research** — Claude Sonnet 5 can summarize cited portfolio news and explain supplied calculations
- **Pre-registered alpha backtests** — Run one locked momentum/trend hypothesis on both FIFO-reconstructed personal acquisition cohorts and point-in-time historical S&P 500 membership, with immutable specifications, source/input hashes, costs, sealed holdouts, and fail-closed market-data and tax coverage
- **Guardrailed streaming AI chat** — Ask portfolio questions without allowing the model to invent actionable buy, sell, or rebalance instructions
- **Multi-broker import** — Nordnet (CSV) and Fidelity ESPP (PDF), with USD→EUR converted on import at each trade's historical ECB rate
- **Manual trade entry & editing** — Record, edit, or delete trades with per-field EUR/USD currency toggles and trade-date FX rates
- **Finnish capital-gains tax suite** — Per-sale ennakkovero calculator for the Fidelity ESPP MSFT position (per-lot hankintameno-olettama, 30 %/34 % bracket), the cumulative year-to-date figures to enter when changing the ennakkovero in OmaVero, a year-to-date €30k capital-income tracker, and per-sale declaration tracking with PDF export
- **Finnish tax-aware accounts** — Arvo-osuustili, OST, ESPP, and Crypto account types
- **Equity performance comparison** — Stock and ETF holdings are compared against the dividend-inclusive S&P 500 Total Return index in EUR; crypto is excluded
- **Market news & alerts** — Price, earnings, rebalance, and news-triggered alerts
- **Investment goals** — Track progress toward financial targets
- **Mobile-responsive UI** — Works on desktop and mobile (Bearer-token auth fallback for browsers that block cross-site cookies)

## Tech Stack

| Layer | Stack |
|-------|-------|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0, PostgreSQL |
| Frontend | React 19, TypeScript, Vite, Tailwind CSS, Recharts |
| Auth | Shared-password gate — HTTP-only `paa_session` cookie (`SameSite=None; Secure`) with `Authorization: Bearer` fallback for mobile |
| AI | Optional Anthropic Claude Sonnet 5 (cited research + streaming chat) |
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
                     ┌────▼──────┐ ┌────▼────┐ │   ┌──────────▼──┐
                     │ Rules/tax │ │yfinance │ │   │  Scheduler  │
                     │ guidance  │ │ + News  │ │   │data/marks  │
                     └────┬──────┘ └────┬────┘ │   └──────┬─────┘
                          │             │      │          │
                     ┌────▼─────────────▼──────▼──────────▼─┐
                     │ Typed snapshots · risk metrics        │
                     │ shadow ledger · backtest evidence     │
                     └──────────┬─────────────────┬───────────┘
                                │                 │ optional
                         ┌──────▼──────┐    ┌─────▼─────┐
                         │  Cockpit   │    │  Claude   │
                         │ no-action  │    │ research  │
                         └──────┬──────┘    └───────────┘
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
| `/api/v1/transactions/tax-calculations` | Saved ennakkovero calcs (MSFT/ESPP only): CRUD, OmaVero declaration tracking, PDF export |
| `/api/v1/analysis` | Deterministic cockpit guidance and refresh, optional shadow AI research, proof-of-value evidence, and alpha backtests |
| `/api/v1/analysis/guidance` | Cockpit snapshot; `/guidance/refresh` updates prices before rebuilding it |
| `/api/v1/analysis/backtests` | Locked specification, ledger coverage, personal/universe execution, and immutable run results |
| `/api/v1/chat` | Streaming AI chat grounded in portfolio context |
| `/api/v1/strategies` | Investment strategy and target allocation |
| `/api/v1/goals` | Investment goals tracking |
| `/api/v1/alerts` | Alert management (price, news, earnings, rebalance) |
| `/api/v1/news` | Market news with impact analysis |
| `/api/v1/settings` | User settings; `/api/v1/fx/eurusd` for historical EUR/USD rates |
| `/api/v1/market-status` | US / Helsinki market open-closed state + next open |
| `/api/v1/upload` | CSV/PDF file import |

### Analysis safety and evidence

The Analysis page shows portfolio health, current exceptions, stance, S&P 500 Total Return comparison, turnover, and tracked Finnish capital-income facts. `POST /analysis/guidance/refresh` refreshes holding prices before rebuilding the view. The return comparison is explicitly gross: it excludes cash, transaction fees, and taxes, so the active-return gap is not labelled net alpha. An investable accumulating-ETF counterfactual remains unavailable until a product and valid tax methodology are configured; ETFs cannot be held in a Finnish OST, and the app does not invent an after-tax result.

The deeper analysis layer optimizes for after-tax, after-cost return relative to the S&P 500 Total Return index in EUR while enforcing user-defined risk limits. It does not infer missing prices, tax lots, costs, expected alpha, or position sizes. A deterministic risk-only engine may emit shadow sell candidates in Advanced evidence when single-position or sector limits are breached, but the consumer cockpit keeps those breaches informational because selling can create immediate tax and transaction-cost drag. Return-seeking buy/sell output remains disabled until a separately validated alpha model exists. Optional AI research can summarize cited news and explain supplied calculations, but it cannot alter the cockpit stance.

Each optional model analysis stores its typed portfolio snapshot plus the complete JSON-safe model request (system prompt, user prompt including normalized news, model, request settings, and deterministic candidates), separate SHA-256 hashes for both, and the validated decision. Model analyses are user-triggered rather than scheduled; market-data/news collection and evaluation of existing shadow outcomes remain scheduled. A run counts as reproducible only when that complete input record is present. Eligible shadow trades are evaluated after 1, 5, 20, and 60 sessions against an explicit cash or benchmark counterfactual, including estimated transaction-cost and tax drag. Risk-enforcement outcomes remain visible but do not count as evidence of alpha. The dashboard requires at least 56 days of collection and 20 distinct **return-seeking** candidate/fill cohorts with 20-session marks before investment evidence is merely **reviewable**; that gate is not a claim of statistical independence, alpha, or permission to trade.

The alpha backtest is separately pre-registered as `alpha-momentum-trend-v1`: monthly 12-minus-1 relative momentum plus a 200-trading-day trend filter, next-close execution, a 20% active sleeve, no parameter search, fixed development/validation/holdout dates, and a moving-block confidence interval. The personal track normalizes stock splits, validates FIFO against current holdings, and tests each pre-purchase signal without future trades; a failed signal preserves 80% of the actual cohort and replaces only the 20% active sleeve with the benchmark. The universe track uses a pinned, hashed point-in-time membership ledger and refuses to run unless `BACKTEST_MARKET_DATA_PATH` supplies every NYSE session and every historical member, including removed/delisted names, as EUR adjusted closes. Deferred-tax evidence can run, but standard taxable-account evidence is explicitly blocked until a future registered data contract includes point-in-time dividend distributions needed for Finnish dividend tax. Historical sectors and forward shadow confirmation also remain mandatory before promotion. Backtests are historical evidence, never proof of future alpha.

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
- `ANTHROPIC_API_KEY` — optional Claude API key for research and chat; deterministic cockpit guidance works without it
- `APP_SECRET` — shared password for the cookie/Bearer access gate (leave empty to disable the gate locally)
- `FINNHUB_API_KEY` — Market news (optional)
- `NEWS_API_KEY` — News aggregation (optional)
- `NTFY_TOPIC` — ntfy.sh topic for push alerts (optional; default `portfolio-alerts`)
- `BACKTEST_MARKET_DATA_PATH` — optional path to a licensed long-form CSV with `date,ticker,adjusted_close_eur`; required for the point-in-time universe track because Yahoo is not accepted as a delisted-security evidence source
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
