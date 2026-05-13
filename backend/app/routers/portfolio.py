import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.portfolio import PerformanceResponse, PortfolioSummary
from app.services.portfolio import compute_performance_comparison, compute_portfolio_summary

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("/summary", response_model=PortfolioSummary)
async def get_portfolio_summary(
    db: AsyncSession = Depends(get_db),
) -> PortfolioSummary:
    """Return aggregated portfolio summary across all accounts.

    Prices are refreshed by the background scheduler (every 5-15 min).
    Use POST /portfolio/refresh-prices for immediate refresh.
    """
    return await compute_portfolio_summary(db)


@router.post("/refresh-prices")
async def refresh_portfolio_prices(db: AsyncSession = Depends(get_db)):
    """Trigger an on-demand price refresh for all holdings."""
    from app.routers.dashboard import invalidate_dashboard_cache
    from app.services.market_data import update_holdings_prices
    updated = await update_holdings_prices(db)
    await db.commit()
    invalidate_dashboard_cache()
    return {"updated": updated}


@router.get("/performance", response_model=PerformanceResponse)
async def get_portfolio_performance(
    period: str = Query("1y", pattern="^(1m|3m|6m|ytd|1y|all)$"),
    db: AsyncSession = Depends(get_db),
) -> PerformanceResponse:
    """Return portfolio vs S&P 500 cumulative return comparison."""
    return await compute_performance_comparison(db, period=period)


@router.get("/sector-breakdown")
async def get_sector_breakdown(db: AsyncSession = Depends(get_db)):
    """Return portfolio allocation grouped by sector/asset class (cached 1h)."""
    import asyncio
    import json
    import logging
    from datetime import datetime, timedelta

    import yfinance as yf
    from sqlalchemy import select

    from app.models.cache import CacheEntry
    from app.models.holding import Holding
    from app.services import symbol_metadata
    from app.services.market_data import _yf_symbol

    logger = logging.getLogger(__name__)

    # Check cache first (1h TTL — values change only when prices refresh)
    cache_key = "sector-breakdown"
    stmt = select(CacheEntry).where(CacheEntry.key == cache_key)
    cached = (await db.execute(stmt)).scalar_one_or_none()
    if cached and cached.expires_at > datetime.utcnow():
        return json.loads(cached.value)

    result = await db.execute(select(Holding))
    holdings = list(result.scalars().all())

    def _fetch_sector_info(symbol: str) -> dict:
        info = symbol_metadata.sector_info(symbol)
        if info is not None:
            return info
        yf_sym = _yf_symbol(symbol)
        try:
            data = yf.Ticker(yf_sym).info
            return {
                "sector": data.get("sector", "Other"),
                "industry": data.get("industry", "Unknown"),
                "country": data.get("country", "Unknown"),
            }
        except Exception as e:
            logger.warning("Failed to fetch sector for %s: %s", symbol, e)
            return {"sector": "Other", "industry": "Unknown", "country": "Unknown"}

    missing = [h.symbol for h in holdings if symbol_metadata.sector_info(h.symbol) is None]
    fetched = {}
    if missing:
        def _fetch_all():
            r = {}
            for sym in missing:
                r[sym] = _fetch_sector_info(sym)
            return r
        fetched = await asyncio.to_thread(_fetch_all)

    # Build sector breakdown
    sector_values: dict[str, float] = {}
    country_values: dict[str, float] = {}
    holdings_by_sector: dict[str, list] = {}
    total_value = 0.0

    for h in holdings:
        value = float(h.current_value_eur or 0)
        if value <= 0:
            continue
        total_value += value
        info = symbol_metadata.sector_info(h.symbol) or fetched.get(h.symbol) or {"sector": "Other", "industry": "Unknown", "country": "Unknown"}
        sector = info["sector"]
        country = info["country"]

        sector_values[sector] = sector_values.get(sector, 0) + value
        country_values[country] = country_values.get(country, 0) + value

        if sector not in holdings_by_sector:
            holdings_by_sector[sector] = []
        holdings_by_sector[sector].append({
            "symbol": h.symbol,
            "value_eur": round(value, 2),
            "weight_pct": 0,
            "industry": info["industry"],
        })

    sectors = []
    for sector, value in sorted(sector_values.items(), key=lambda x: x[1], reverse=True):
        pct = round(value / total_value * 100, 1) if total_value else 0
        sector_holdings = holdings_by_sector.get(sector, [])
        for sh in sector_holdings:
            sh["weight_pct"] = round(sh["value_eur"] / total_value * 100, 1) if total_value else 0
        sectors.append({
            "sector": sector,
            "value_eur": round(value, 2),
            "weight_pct": pct,
            "holdings": sector_holdings,
        })

    countries = []
    for country, value in sorted(country_values.items(), key=lambda x: x[1], reverse=True):
        pct = round(value / total_value * 100, 1) if total_value else 0
        countries.append({
            "country": country,
            "value_eur": round(value, 2),
            "weight_pct": pct,
        })

    response_data = {
        "total_value_eur": round(total_value, 2),
        "sectors": sectors,
        "countries": countries,
    }

    # Cache for 1 hour
    if cached:
        cached.value = json.dumps(response_data)
        cached.expires_at = datetime.utcnow() + timedelta(hours=1)
    else:
        db.add(CacheEntry(key=cache_key, value=json.dumps(response_data), expires_at=datetime.utcnow() + timedelta(hours=1)))
    await db.commit()

    return response_data


@router.get("/earnings-calendar")
async def get_earnings_calendar(db: AsyncSession = Depends(get_db)):
    """Return upcoming earnings dates for portfolio holdings (cached 24h)."""
    import asyncio
    import json
    import logging
    from datetime import datetime, timedelta

    import yfinance as yf
    from sqlalchemy import select

    from app.models.cache import CacheEntry
    from app.models.holding import Holding
    from app.services.market_data import _yf_symbol
    from app.services import symbol_metadata as symbol_metadata_service

    logger = logging.getLogger(__name__)

    # Check cache first
    cache_key = "earnings-calendar"
    stmt = select(CacheEntry).where(CacheEntry.key == cache_key)
    cached = (await db.execute(stmt)).scalar_one_or_none()
    if cached and cached.expires_at > datetime.utcnow():
        # Filter out past dates (cache may span midnight)
        cached_data = json.loads(cached.value)
        today_str = datetime.now().date().isoformat()
        cached_data["events"] = [e for e in cached_data.get("events", []) if e["date"] >= today_str]
        return cached_data

    result = await db.execute(select(Holding))
    holdings = list(result.scalars().all())

    # Skip symbols flagged as non-earnings (crypto, ETFs)
    equity_symbols = [
        h.symbol for h in holdings
        if not symbol_metadata_service.skip_in_aggregations(h.symbol)
        and (h.current_value_eur or 0) > 0
    ]

    def _fetch_earnings():
        events = []
        for symbol in equity_symbols:
            yf_sym = _yf_symbol(symbol)
            try:
                ticker = yf.Ticker(yf_sym)
                cal = ticker.calendar
                if cal is not None and not (hasattr(cal, 'empty') and cal.empty):
                    # calendar can be a dict or DataFrame
                    if isinstance(cal, dict):
                        earnings_date = cal.get("Earnings Date")
                        if earnings_date:
                            if isinstance(earnings_date, list):
                                for ed in earnings_date:
                                    events.append({"symbol": symbol, "date": str(ed)[:10], "event": "Earnings"})
                            else:
                                events.append({"symbol": symbol, "date": str(earnings_date)[:10], "event": "Earnings"})
                    else:
                        # DataFrame format
                        if "Earnings Date" in cal.columns:
                            for ed in cal["Earnings Date"]:
                                events.append({"symbol": symbol, "date": str(ed)[:10], "event": "Earnings"})
                        elif "Earnings Date" in cal.index:
                            val = cal.loc["Earnings Date"]
                            if hasattr(val, '__iter__') and not isinstance(val, str):
                                for v in val:
                                    events.append({"symbol": symbol, "date": str(v)[:10], "event": "Earnings"})
                            else:
                                events.append({"symbol": symbol, "date": str(val)[:10], "event": "Earnings"})
            except Exception as e:
                logger.warning("Failed to fetch earnings for %s: %s", symbol, e)
        return events

    events = await asyncio.to_thread(_fetch_earnings)

    # Sort by date and filter to next 90 days
    today = datetime.now().date()
    cutoff = today + timedelta(days=90)
    upcoming = [
        e for e in events
        if e["date"] >= today.isoformat() and e["date"] <= cutoff.isoformat()
    ]
    upcoming.sort(key=lambda x: x["date"])

    response_data = {"events": upcoming}

    # Store in cache (24h TTL)
    import uuid
    if cached:
        cached.value = json.dumps(response_data)
        cached.expires_at = datetime.utcnow() + timedelta(hours=24)
    else:
        db.add(CacheEntry(
            id=uuid.uuid4(),
            key=cache_key,
            value=json.dumps(response_data),
            expires_at=datetime.utcnow() + timedelta(hours=24),
        ))
    await db.flush()

    return response_data
