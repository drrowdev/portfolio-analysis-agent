from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.routers import accounts, alerts, analysis, chat, dashboard, goals, holdings, market_status, news, portfolio, settings, strategy, tax_calculations, transactions, upload
from app.routers.gate import router as gate_router, is_authenticated


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Startup — create tables for local SQLite dev
    from app.database import engine, init_db
    from app.services import symbol_metadata as symbol_metadata_cache
    from app.services.scheduler import setup_scheduler, shutdown_scheduler

    await init_db()
    await symbol_metadata_cache.reload_cache()
    setup_scheduler()
    yield
    # Shutdown
    shutdown_scheduler()
    await engine.dispose()


app = FastAPI(
    title="Portfolio Analysis Agent",
    version="0.1.0",
    lifespan=lifespan,
)

import os

CORS_ORIGINS = [
    "http://localhost:5173",
]
# Production frontend origins are injected via the CORS_ORIGINS env var
# on the Container App. Don't hardcode production hostnames here.
if os.environ.get("CORS_ORIGINS"):
    CORS_ORIGINS.extend(os.environ["CORS_ORIGINS"].split(","))

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def gate_middleware(request: Request, call_next):
    """Reject unauthenticated requests (except login/health/check endpoints).

    CORS preflight (OPTIONS) requests are always allowed through so the
    CORSMiddleware downstream can answer them. Preflight requests do not
    carry the auth cookie, so gating them would break every cross-origin
    GET/POST/etc. from the SWA frontend.
    """
    # Always allow CORS preflight — CORSMiddleware will respond appropriately.
    if request.method == "OPTIONS":
        return await call_next(request)
    path = request.url.path
    # Allow auth endpoints and health check through without cookie
    if path in ("/health", "/api/v1/auth/login", "/api/v1/auth/check"):
        return await call_next(request)
    if not is_authenticated(request):
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    return await call_next(request)


app.include_router(gate_router, prefix="/api/v1")

app.include_router(dashboard.router, prefix="/api/v1")
app.include_router(accounts.router, prefix="/api/v1")
app.include_router(holdings.router, prefix="/api/v1")
app.include_router(upload.router, prefix="/api/v1")
app.include_router(portfolio.router, prefix="/api/v1")
app.include_router(strategy.router, prefix="/api/v1")
app.include_router(goals.router, prefix="/api/v1")
app.include_router(alerts.router, prefix="/api/v1")
app.include_router(analysis.router, prefix="/api/v1")
app.include_router(news.router, prefix="/api/v1")
app.include_router(market_status.router, prefix="/api/v1")
app.include_router(settings.router, prefix="/api/v1")
app.include_router(settings.fx_router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(transactions.router, prefix="/api/v1")
app.include_router(tax_calculations.router, prefix="/api/v1")


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}
