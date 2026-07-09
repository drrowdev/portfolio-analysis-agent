# Portfolio Analysis Agent — Frontend

React 19 + TypeScript single-page app for the Portfolio Analysis Agent. Bundled with **Vite** and deployed to **Azure Static Web Apps** (Free tier); it talks to the FastAPI backend cross-origin.

> For the full-stack overview, architecture, and backend setup, see the [root README](../README.md).

## Tech Stack

- **React 19** + **TypeScript**, bundled with **Vite**
- **TanStack Router** for routing, **TanStack Query** for server state & caching
- **Tailwind CSS v4** with **Radix UI** primitives and **lucide-react** icons
- **Recharts** for portfolio/performance charts, **react-markdown** for AI output

## Local Development

```bash
npm install
npm run dev      # http://localhost:5173
```

The dev server proxies `/api` to the local backend at `http://localhost:8000` (see `vite.config.ts`), so run the backend alongside it (instructions in the root README).

### Scripts

| Script | Purpose |
|--------|---------|
| `npm run dev` | Start the Vite dev server with HMR |
| `npm run build` | Type-check (`tsc -b`) then build to `dist/` |
| `npm run preview` | Serve the production build locally |
| `npm run lint` | Run ESLint |

## Environment

- `VITE_API_BASE_URL` — backend API base URL, baked in at **build time**. Defaults to `/api/v1` (the Vite dev proxy) for local dev. In CI it is set from the `VITE_API_BASE_URL` GitHub repo Variable to the deployed Container App URL.

Auth is a shared-password gate: the login call returns a token stored as an HTTP-only `paa_session` cookie, with an `Authorization: Bearer` fallback for browsers that block cross-site cookies (iOS Safari, mobile Firefox). All requests go through the central client in `src/lib/api.ts`, which sends `credentials: 'include'`.

## Structure

```
src/
├── main.tsx        # App entry
├── App.tsx         # Router + providers
├── pages/          # Route pages (dashboard, holdings, transactions, alerts, …)
├── components/     # UI primitives + portfolio components
├── hooks/          # TanStack Query hooks
├── contexts/       # React contexts
├── lib/            # api client + utils (formatDate/formatCurrency pinned to fi-FI)
└── types/          # Shared TypeScript types
```

## Deployment

Pushing to `main` triggers `.github/workflows/deploy.yml`, which builds `dist/` (with `VITE_API_BASE_URL` injected) and deploys to Azure Static Web Apps via `Azure/static-web-apps-deploy@v1`. Client-side routes fall back to `index.html` through `public/staticwebapp.config.json`, which is copied into `dist/` at build time.
