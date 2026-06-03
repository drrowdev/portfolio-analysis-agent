# Changelog

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- **Frontend hosting** — migrated React frontend from Azure Container Apps (nginx) to Azure Static Web Apps (Free tier). The frontend now calls the backend cross-origin via the `VITE_API_BASE_URL` build-time variable; the auth cookie uses `SameSite=None; Secure`. Cuts hosting cost by ~€19/month and adds a global CDN. CI builds with `VITE_API_BASE_URL` from a GitHub repo Variable and deploys via `azure/static-web-apps-deploy@v1`. The old `portfolio-frontend` Container App, its nginx proxy, and the frontend Dockerfile have been removed.

### Added
- **Delete / re-run saved tax calculations** — added the ability to remove saved ennakkovero calculations so they can be re-run after a logic correction. New `DELETE /transactions/tax-calculations/{id}` (single) and `DELETE /transactions/tax-calculations/` (bulk, optional `symbol`/`year` filters) endpoints. The Transaction History page now shows a per-row trash icon next to each saved sell calculation and a "Delete tax calcs (N)" button in the header (both confirm first). Saving is now **idempotent**: re-running the same sale replaces its previous calculation (matched by linked transaction, else by symbol + sell date + quantity) instead of creating a duplicate row.
- **Automatic USD→EUR FX conversion on import** — Fidelity ESPP statements are USD-native, so imported transactions previously kept raw USD figures in their EUR fields until the user manually ran `POST /transactions/fix-fx-rates/{symbol}`. The Fidelity upload now converts every transaction to EUR automatically using the historical ECB reference rate for each transaction's own date (frankfurter.app), so cost basis and the ennakkovero calculation are tax-ready immediately. The conversion is extracted into a reusable, unit-tested service (`app/services/fx.py`); the manual endpoint now reuses it as a re-run/fallback. The conversion is best-effort — an FX-API outage logs a warning and leaves the import intact (re-run the endpoint later). The upload response includes an `fx_conversion` summary.
- **Cookie-based password gate** — simple shared-secret auth replacing MSAL for personal use. No more Azure AD token acquisition on page load; login is a single password prompt stored as an HTTP-only cookie.
- **Keep-alive cron** — GitHub Actions workflow pings the backend every 5 minutes (the shortest reliable GH Actions interval) to prevent Container Apps cold starts.

### Fixed
- **QuickTrade USD-before-rate guard** — submitting a USD trade via the Enter key could bypass the disabled submit button and pass the raw USD price through as EUR (the `priceEur` fallback) when the sale-day EUR/USD rate hadn't loaded yet, inflating the cost basis / ennakkovero. `handleSubmit` now blocks USD trades (and USD fees) until the rate is available and shows a "waiting for exchange rate" toast.
- **Ennakkovero 10-year boundary now calendar-based**— the hankintameno-olettama rate (40 % for lots held ≥10 years, 20 % otherwise) is now determined by calendar arithmetic (the lot's exact 10-year anniversary date) instead of a `days / 365.25` approximation, which could misclassify a lot by ~1 day right at the boundary and flip the deemed-cost rate. Leap-day lots (Feb 29) fall back to Feb 28 in a non-leap target year. Extracted into pure helpers `ten_year_anniversary()` / `held_at_least_10_years()` in `app/services/tax.py` with regression tests (`tests/test_holding_period.py`).
- **Ennakkovero guidance notes corrected** — replaced the incorrect "file an ennakkoveroilmoitus within 2 months of the sale" note with the correct lisäennakko (additional prepayment) guidance: pay in MyTax without interest by the end of January following the tax year (e.g. a 2026 sale → by 31 Jan 2027), minimum €170, with relief interest accruing thereafter. Added notes surfacing the €1,000 small-disposals exemption (TVL 48.6 §, a per-year aggregate the calculator cannot see) and clarifying that the 30 %/34 % bracket depends on the taxpayer's whole-year capital income (dividends, rental, other gains) and deductible losses — verified against the Finnish Tax Administration's guidance and the KPMG "Taxation of the Stock Awards in FI" memo.
- **Ennakkovero per-lot hankintameno-olettama** — the capital-gains tax calculation(`/transactions/tax-calculation`) now applies the deemed acquisition cost (hankintameno-olettama) **per lot** by each lot's own holding period (40 % for lots held ≥10 years, 20 % otherwise) and lets each lot independently choose the cheaper of actual vs. deemed cost. Previously a single recent lot forced the whole sale to the 20 % rate (`all_over_10` bug), overstating the taxable gain and overpaying tax (~€2,400 on a representative mixed-lot MSFT sale). Added a lot-coverage guard: if recorded buy lots cover fewer shares than were sold, the shortfall shares now get the 20 % olettama and a loud warning instead of a silently understated cost basis. The math is extracted into a pure, unit-tested module (`app/services/tax.py`) with regression tests (`tests/test_tax.py`). Output adds `hankintameno_kaytetty` (effective deduction), a `coverage` block, and per-lot `applied_deemed_rate`/`method`; `recommended_method` may now be `yhdistelma` (mixed).
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
