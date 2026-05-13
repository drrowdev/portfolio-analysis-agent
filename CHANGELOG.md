# Changelog

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- **Frontend hosting** — migrated React frontend from Azure Container Apps (nginx) to Azure Static Web Apps (Free tier). The frontend now calls the backend cross-origin via the `VITE_API_BASE_URL` build-time variable; the auth cookie uses `SameSite=None; Secure`. Cuts hosting cost by ~€19/month and adds a global CDN. CI builds with `VITE_API_BASE_URL` from a GitHub repo Variable and deploys via `azure/static-web-apps-deploy@v1`. The old `portfolio-frontend` Container App, its nginx proxy, and the frontend Dockerfile have been removed.

### Added
- **Cookie-based password gate** — simple shared-secret auth replacing MSAL for personal use. No more Azure AD token acquisition on page load; login is a single password prompt stored as an HTTP-only cookie.
- **Keep-alive cron** — GitHub Actions workflow pings the backend every 5 minutes (the shortest reliable GH Actions interval) to prevent Container Apps cold starts.

### Fixed
- **FIFO cost basis** — switched P/L calculation from average cost to FIFO (First In, First Out), matching Fidelity and Finnish tax rules. Previously, selling old cheap ESPP lots didn't properly remove their low cost basis, overstating unrealized P/L by ~€21k.
- **Dashboard 500 error** — removed shadowed `JSONResponse` import that caused the combined dashboard endpoint to crash.
- **Mobile card truncation** — summary cards (PortfolioSummary, DailySummary, CashAvailable) no longer truncate values on narrow viewports.
- **Stale earnings calendar** — cached earnings data now filters out past dates at response time, and frontend guards against negative `daysUntil` values. Previously, 24h-cached data could show yesterday's earnings after midnight.

### Changed
- **Auth simplification** — removed MSAL authentication entirely; the app now uses a lightweight cookie-based password gate. This eliminates the Azure AD app registration dependency and speeds up page load significantly.
- **Container Apps scaling** — reverted to `min_replicas: 0` (scale-to-zero) with a GitHub Actions keep-alive cron instead of always-on instances, saving ~€17/month.

### Changed
- **Performance** — removed blocking price refresh from API request path; dashboard now loads instantly from cached data. Scheduler refreshes prices every 5 min during US market hours (was 15 min). Sector breakdown cached 1h. Frontend uses lazy loading and code splitting for ~50% faster initial paint.
- **Performance** — combined dashboard endpoint (`/api/v1/dashboard`) returns all above-fold data in a single request, eliminating 6 parallel network round-trips. Added 2 uvicorn workers. Sidebar deduplicates portfolio summary fetch.

### Added
- **Tax calculation persistence** — ennakkovero calculations are now saved to the database with auto-linking to the matching sell transaction.
- **PDF export** — "Save" then "Download PDF" buttons in the tax calculation dialog generate a Finnish ennakkovero PDF (OmaVero-ready).
- **Tax calc link on transactions** — sell rows in Transaction History show a 📄 icon; blue = saved calculation exists, click to view/recalculate.
- New backend router `transactions/tax-calculations` with CRUD + PDF generation (reportlab).
- New `tax_calculations` table + Alembic migration.
- `AGENTS.md` onboarding document with doc-update policy table and common pitfalls, so README/CHANGELOG/architecture stay in sync without a cron job.
- `CHANGELOG.md` with retroactive `[1.0.0]` entry.

## [1.0.0] — Initial release

### Added
- FastAPI backend with routers for accounts, holdings, portfolio, transactions, analysis, chat, strategy, goals, alerts, news, settings, upload, kraken, and market status.
- React 19 + Vite + TypeScript frontend with Tailwind CSS and Recharts.
- Microsoft MSAL (Personal Account) authentication with JWT RS256.
- Anthropic Claude integration: streaming chat + scheduled daily analysis, rebalance, and tax-optimization summaries.
- Multi-broker import (Nordnet, Fidelity, Kraken) via CSV/PDF.
- Finnish tax-aware account types (AOT, OST, ESPP, Crypto).
- Market data via yfinance with on-disk cache; news via Finnhub and NewsAPI.
- Investment goals tracking and alert engine (price, news, earnings, rebalance).
- Mobile-responsive dashboard.
- PostgreSQL persistence with Alembic migrations.
- GitHub Actions CI/CD: Docker build → ACR push → Azure Container Apps deploy.

[Unreleased]: https://github.com/drrowdev/portfolio-analysis-agent/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/drrowdev/portfolio-analysis-agent/releases/tag/v1.0.0
