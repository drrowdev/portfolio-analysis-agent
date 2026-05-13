"""Combined dashboard endpoint — single request for all above-fold data."""

import logging
import time

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.account import Account
from app.models.alert import AnalysisHistory, AnalysisType
from app.models.holding import Holding
from app.services.portfolio import compute_portfolio_summary

logger = logging.getLogger(__name__)

router = APIRouter(tags=["dashboard"])

# In-memory cache for dashboard response (avoids repeated DB queries)
_dashboard_cache: dict[str, tuple[float, dict]] = {}
_DASHBOARD_CACHE_TTL = 60  # seconds


def invalidate_dashboard_cache():
    """Call this after price refresh or manual data changes."""
    _dashboard_cache.clear()


@router.get("/dashboard")
async def get_dashboard(db: AsyncSession = Depends(get_db)):
    """Return all data needed for initial dashboard render in a single response.

    Combines: portfolio/summary, holdings, accounts, market-status,
    latest-daily-summary, and cash_available setting.
    Response is cached in-memory for 60s to avoid repeated DB queries.
    """
    # Check in-memory cache
    now = time.time()
    cached = _dashboard_cache.get("data")
    if cached and (now - cached[0]) < _DASHBOARD_CACHE_TTL:
        return JSONResponse(
            content=cached[1],
            headers={"Cache-Control": "private, max-age=30"},
        )

    try:
        # Compute portfolio summary first (uses selectinload on the session)
        summary = await compute_portfolio_summary(db)
        summary_data = summary.model_dump(mode="json")

        # Then run remaining queries sequentially on same session
        holdings_result = await db.execute(select(Holding))
        holdings = list(holdings_result.scalars().all())

        accounts_result = await db.execute(select(Account))
        accounts = list(accounts_result.scalars().all())

        daily_stmt = (
            select(AnalysisHistory)
            .where(AnalysisHistory.analysis_type == AnalysisType.daily_summary)
            .order_by(AnalysisHistory.created_at.desc())
            .limit(1)
        )
        daily_result = await db.execute(daily_stmt)
        daily_row = daily_result.scalar_one_or_none()

        # Market status (pure computation, no DB/network)
        from app.routers.market_status import get_market_status
        market_status = await get_market_status()

        # Build response
        daily_summary = None
        if daily_row:
            daily_summary = {
                "id": str(daily_row.id),
                "analysis_type": daily_row.analysis_type.value,
                "content": daily_row.content,
                "created_at": daily_row.created_at.isoformat() + "Z",
            }

        holdings_data = [
            {
                "id": str(h.id),
                "account_id": str(h.account_id),
                "symbol": h.symbol,
                "instrument_name": h.instrument_name,
                "isin": h.isin,
                "currency": h.currency,
                "exchange": h.exchange,
                "total_quantity": float(h.total_quantity) if h.total_quantity else 0,
                "avg_cost_basis_eur": float(h.avg_cost_basis_eur) if h.avg_cost_basis_eur else 0,
                "total_cost_eur": float(h.total_cost_eur) if h.total_cost_eur else 0,
                "current_price_native": float(h.current_price_native) if h.current_price_native else None,
                "current_price_eur": float(h.current_price_eur) if h.current_price_eur else None,
                "current_value_eur": float(h.current_value_eur) if h.current_value_eur else None,
                "unrealized_pnl_eur": float(h.unrealized_pnl_eur) if h.unrealized_pnl_eur else None,
                "unrealized_pnl_pct": float(h.unrealized_pnl_pct) if h.unrealized_pnl_pct else None,
                "portfolio_weight_pct": float(h.portfolio_weight_pct) if h.portfolio_weight_pct else None,
                "price_change_pct": float(h.price_change_pct) if h.price_change_pct else None,
                "market_state": h.market_state,
                "extended_hours_price": float(h.extended_hours_price) if h.extended_hours_price else None,
                "extended_hours_change_pct": float(h.extended_hours_change_pct) if h.extended_hours_change_pct else None,
                "last_price_update": h.last_price_update.isoformat() if h.last_price_update else None,
            }
            for h in holdings
        ]

        accounts_data = [
            {
                "id": str(a.id),
                "name": a.name,
                "broker": a.broker,
                "account_type": a.account_type.value if hasattr(a.account_type, 'value') else a.account_type,
                "currency": a.currency,
                "tax_treatment": a.tax_treatment.value if hasattr(a.tax_treatment, 'value') else a.tax_treatment,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in accounts
        ]

        response_data = {
            "summary": summary_data,
            "holdings": holdings_data,
            "accounts": accounts_data,
            "market_status": market_status,
            "daily_summary": daily_summary,
        }

        # Store in cache
        _dashboard_cache["data"] = (time.time(), response_data)

        return JSONResponse(
            content=response_data,
            headers={"Cache-Control": "private, max-age=30"},
        )
    except Exception as e:
        logger.exception("Dashboard endpoint failed")
        return JSONResponse(
            status_code=500,
            content={"detail": f"{type(e).__name__}: {str(e)}"},
        )
