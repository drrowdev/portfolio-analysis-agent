"""Portfolio aggregation and P/L calculations."""

import asyncio
import logging
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pandas as pd
import yfinance as yf
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.account import Account
from app.models.holding import Holding
from app.models.transaction import Transaction, TransactionType
from app.schemas.portfolio import (
    AccountSummary,
    AllocationEntry,
    PerformanceDataPoint,
    PerformanceResponse,
    PortfolioSummary,
)
from app.services.market_data import _yf_symbol as _yf_symbol_lookup

logger = logging.getLogger(__name__)

DEFAULT_EURUSD = Decimal("1.13")  # fallback EURUSD rate (USD per 1 EUR)

# Simple in-memory cache: key → (timestamp, data)
_performance_cache: dict[str, tuple[float, PerformanceResponse]] = {}
_CACHE_TTL = 2 * 60 * 60  # 2 hours


async def compute_portfolio_summary(db: AsyncSession) -> PortfolioSummary:
    """Aggregate holdings across all accounts into a portfolio summary."""
    # Load all accounts with their holdings
    stmt = select(Account).options(selectinload(Account.holdings))
    result = await db.execute(stmt)
    accounts = list(result.scalars().all())

    # Fetch cash available from user settings
    from app.models.user_settings import UserSetting
    cash_result = await db.execute(
        select(UserSetting).where(UserSetting.key == "cash_available")
    )
    cash_setting = cash_result.scalar_one_or_none()
    cash_available = Decimal(cash_setting.value) if cash_setting else Decimal("0")

    total_value = Decimal("0")
    total_cost = Decimal("0")
    daily_pnl = Decimal("0")
    account_summaries: list[AccountSummary] = []
    all_holdings: list[dict] = []

    for account in accounts:
        acct_value = Decimal("0")
        acct_cost = Decimal("0")

        for holding in account.holdings:
            # All holding values (*_eur fields) are already in EUR
            cost_eur = holding.total_cost_eur or Decimal("0")
            value_eur = holding.current_value_eur or cost_eur

            acct_cost += cost_eur
            acct_value += value_eur

            # Calculate today's change for this holding
            if holding.price_change_pct is not None and value_eur > 0:
                # value_eur = qty * current_price; yesterday's value = value_eur / (1 + change%)
                change_factor = holding.price_change_pct / Decimal("100")
                daily_change = value_eur - (value_eur / (1 + change_factor))
                daily_pnl += daily_change

            all_holdings.append({
                "symbol": holding.symbol,
                "instrument_name": holding.instrument_name,
                "value_eur": value_eur,
                "cost_eur": cost_eur,
            })

        acct_pnl = acct_value - acct_cost
        acct_pnl_pct = (
            (acct_pnl / acct_cost * 100) if acct_cost else None
        )

        account_summaries.append(
            AccountSummary(
                account_id=str(account.id),
                account_name=account.name,
                broker=account.broker,
                total_value_eur=acct_value.quantize(Decimal("0.01")),
                total_cost_eur=acct_cost.quantize(Decimal("0.01")),
                unrealized_pnl_eur=acct_pnl.quantize(Decimal("0.01")),
                unrealized_pnl_pct=(
                    acct_pnl_pct.quantize(Decimal("0.01")) if acct_pnl_pct else None
                ),
            )
        )

        total_value += acct_value
        total_cost += acct_cost

    # Add cash to total value (cash is not a cost/investment, so only add to value)
    total_value_with_cash = total_value + cash_available

    total_pnl = total_value - total_cost
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost else None

    # Build allocation entries sorted by value — weights based on total including cash
    top_holdings: list[AllocationEntry] = []
    for h in sorted(all_holdings, key=lambda x: x["value_eur"], reverse=True):
        weight = (h["value_eur"] / total_value_with_cash * 100) if total_value_with_cash else Decimal("0")
        top_holdings.append(
            AllocationEntry(
                symbol=h["symbol"],
                instrument_name=h["instrument_name"],
                weight_pct=weight.quantize(Decimal("0.01")),
                value_eur=h["value_eur"].quantize(Decimal("0.01")),
            )
        )

    # Compute daily P&L percentage relative to yesterday's portfolio value
    yesterday_value = total_value - daily_pnl
    daily_pnl_pct = (daily_pnl / yesterday_value * 100) if yesterday_value else None

    return PortfolioSummary(
        total_value_eur=total_value_with_cash.quantize(Decimal("0.01")),
        total_cost_eur=total_cost.quantize(Decimal("0.01")),
        total_unrealized_pnl_eur=total_pnl.quantize(Decimal("0.01")),
        total_unrealized_pnl_pct=(
            total_pnl_pct.quantize(Decimal("0.01")) if total_pnl_pct else None
        ),
        daily_pnl_eur=daily_pnl.quantize(Decimal("0.01")),
        daily_pnl_pct=(
            daily_pnl_pct.quantize(Decimal("0.01")) if daily_pnl_pct else None
        ),
        cash_available=cash_available.quantize(Decimal("0.01")),
        accounts=account_summaries,
        top_holdings=top_holdings,
    )


# ---------------------------------------------------------------------------
# Performance comparison: portfolio vs S&P 500
# ---------------------------------------------------------------------------

PERIOD_MAP = {
    "1m": 30,
    "3m": 90,
    "6m": 180,
    "1y": 365,
}


def _resolve_period(period: str, earliest_tx_date: date) -> date:
    """Return the start date for the requested period."""
    today = date.today()
    period = period.lower()
    if period == "ytd":
        return date(today.year, 1, 1)
    if period == "all":
        return earliest_tx_date
    days = PERIOD_MAP.get(period, 365)
    return today - timedelta(days=days)


def _yf_symbol(symbol: str) -> str:
    return _yf_symbol_lookup(symbol)


def _compute_performance_sync(
    transactions: list[dict[str, Any]],
    holdings_info: list[dict[str, Any]],
    period: str,
) -> PerformanceResponse:
    """Heavy synchronous work: fetch yfinance data and compute returns.

    ``transactions`` – list of dicts with keys: symbol, date, quantity, transaction_type, currency
    ``holdings_info`` – list of dicts with keys: symbol, currency
    """
    if not transactions:
        return PerformanceResponse(period=period, start_date=date.today(), data=[])

    # Sort transactions by date
    transactions.sort(key=lambda t: t["date"])
    earliest_tx = transactions[0]["date"]
    start = _resolve_period(period, earliest_tx)
    today = date.today()
    end = today + timedelta(days=1)  # yfinance end is exclusive

    # Clamp start to earliest transaction
    if start < earliest_tx:
        start = earliest_tx

    # Collect unique symbols and their currencies
    symbol_currencies: dict[str, str] = {}
    for h in holdings_info:
        symbol_currencies[h["symbol"]] = h["currency"]
    for t in transactions:
        if t["symbol"] not in symbol_currencies:
            symbol_currencies[t["symbol"]] = t["currency"]

    symbols = list(symbol_currencies.keys())
    if not symbols:
        return PerformanceResponse(period=period, start_date=start, data=[])

    # Fetch historical prices for all symbols + S&P 500 + EUR/USD
    yf_symbols = [_yf_symbol(s) for s in symbols]
    all_tickers = yf_symbols + ["^GSPC", "EURUSD=X"]

    try:
        raw = yf.download(
            all_tickers,
            start=str(start),
            end=str(end),
            auto_adjust=True,
            progress=False,
        )
    except Exception as e:
        logger.error("yfinance download failed: %s", e)
        return PerformanceResponse(period=period, start_date=start, data=[])

    if raw.empty:
        return PerformanceResponse(period=period, start_date=start, data=[])

    # Extract Close prices — handle both single and multi-ticker column formats
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"] if "Close" in raw.columns.get_level_values(0) else raw
    else:
        close = raw[["Close"]].rename(columns={"Close": all_tickers[0]}) if len(all_tickers) == 1 else raw

    # Flatten column index if needed (yfinance sometimes returns Ticker as second level)
    if isinstance(close.columns, pd.MultiIndex):
        close.columns = close.columns.get_level_values(-1)

    close = close.ffill()  # forward-fill gaps (holidays, missing data)

    # Build a mapping from our symbol to yfinance symbol
    sym_to_yf = {s: _yf_symbol(s) for s in symbols}

    # Get EUR/USD rate series
    eurusd_col = "EURUSD=X"
    if eurusd_col in close.columns:
        eurusd_series = close[eurusd_col]
    else:
        eurusd_series = pd.Series(float(DEFAULT_EURUSD), index=close.index)

    sp500_col = "^GSPC"
    if sp500_col not in close.columns:
        return PerformanceResponse(period=period, start_date=start, data=[])

    sp500 = close[sp500_col]

    # Build position quantities over time from transactions
    # For each date, quantity[symbol] = cumulative buys - cumulative sells up to that date
    tx_by_date: dict[date, list[dict]] = defaultdict(list)
    for t in transactions:
        tx_by_date[t["date"]].append(t)

    # Trading days in our index
    trading_days = close.index.tolist()
    if not trading_days:
        return PerformanceResponse(period=period, start_date=start, data=[])

    # Build cumulative positions for each trading day
    # Track both positions and cumulative cost (inflows) to compute true returns
    positions: dict[str, float] = defaultdict(float)
    tx_dates_sorted = sorted(tx_by_date.keys())
    tx_idx = 0

    # --- Time-Weighted Return (TWRR) via two-pass approach ---
    # Pass 1: Build daily values and detect cash flow days
    # Pass 2: Chain sub-period returns, splitting at cash flow days

    def _portfolio_value_at(ts_inner, positions_inner, eurusd_rate_inner):
        """Calculate portfolio value for given positions."""
        val = 0.0
        for sym_inner, qty_inner in positions_inner.items():
            if qty_inner <= 0:
                continue
            yf_sym_inner = sym_to_yf.get(sym_inner, sym_inner)
            if yf_sym_inner not in close.columns:
                continue
            price_inner = close[yf_sym_inner].get(ts_inner)
            if price_inner is None or pd.isna(price_inner):
                continue
            v = float(price_inner) * qty_inner
            if symbol_currencies.get(sym_inner, "EUR") == "USD":
                v /= eurusd_rate_inner
            val += v
        return val

    daily_records: list[dict] = []# {day, ts, portfolio_value, sp500_eur, has_flow, value_before_flow}

    for ts in trading_days:
        day = ts.date() if hasattr(ts, "date") else ts

        eurusd_rate = float(eurusd_series.get(ts, float(DEFAULT_EURUSD)))
        if pd.isna(eurusd_rate) or eurusd_rate == 0:
            eurusd_rate = float(DEFAULT_EURUSD)

        # Compute value BEFORE applying any transactions for today
        value_before = _portfolio_value_at(ts, positions, eurusd_rate)

        # Apply all transactions up to and including this day
        has_flow = False
        while tx_idx < len(tx_dates_sorted) and tx_dates_sorted[tx_idx] <= day:
            for t in tx_by_date[tx_dates_sorted[tx_idx]]:
                qty = float(t["quantity"])
                is_position_adj = t.get("notes", "").startswith("Position adjustment") or t.get("notes", "").startswith("Opening balance")
                if t["transaction_type"] in ("buy", "espp_purchase", "deposit"):
                    positions[t["symbol"]] += qty
                    if not is_position_adj:
                        has_flow = True
                elif t["transaction_type"] in ("sell", "espp_sale", "withdrawal"):
                    positions[t["symbol"]] -= qty
                    if not is_position_adj:
                        has_flow = True
            tx_idx += 1

        # Compute value AFTER transactions
        portfolio_value = _portfolio_value_at(ts, positions, eurusd_rate)

        sp500_val = float(sp500.get(ts, 0))
        if pd.isna(sp500_val):
            continue

        sp500_eur = sp500_val / eurusd_rate

        daily_records.append({
            "day": day,
            "portfolio_value": portfolio_value,
            "sp500_eur": sp500_eur,
            "has_flow": has_flow,
            "value_before_flow": value_before if has_flow else None,
        })

    # Pass 2: Chain TWRR
    data_points: list[PerformanceDataPoint] = []
    first_sp500_eur: float | None = None
    twrr_cumulative: float = 1.0
    prev_end_value: float | None = None  # end-of-day value (post-flow) from previous day

    for rec in daily_records:
        pv = rec["portfolio_value"]
        sp_eur = rec["sp500_eur"]

        if prev_end_value is None:
            if pv > 0:
                prev_end_value = pv
                first_sp500_eur = sp_eur
            continue

        if rec["has_flow"]:
            # On flow day: chain the return up to BEFORE the flow
            # (using old positions at today's prices)
            vbf = rec["value_before_flow"]
            if vbf is not None and vbf > 0 and prev_end_value > 0:
                sub_return = vbf / prev_end_value
                twrr_cumulative *= sub_return
            # Reset base to post-flow value
            prev_end_value = pv
        else:
            # Normal day: chain the daily return
            if prev_end_value > 0 and pv > 0:
                daily_return = pv / prev_end_value
                twrr_cumulative *= daily_return
            prev_end_value = pv

        if first_sp500_eur is None or first_sp500_eur == 0:
            continue

        port_ret = (twrr_cumulative - 1) * 100
        sp_ret = (sp_eur / first_sp500_eur - 1) * 100

        data_points.append(
            PerformanceDataPoint(
                date=rec["day"],
                portfolio_return_pct=round(port_ret, 2),
                sp500_return_pct=round(sp_ret, 2),
                portfolio_value_eur=round(pv, 2),
            )
        )

    return PerformanceResponse(
        period=period,
        start_date=start,
        data=data_points,
    )


async def compute_performance_comparison(
    db: AsyncSession,
    period: str = "1y",
) -> PerformanceResponse:
    """Return portfolio vs S&P 500 performance data, with persistent DB caching."""
    import json

    from sqlalchemy import select as sa_select

    from app.models.cache import CacheEntry

    cache_key = f"performance-{period.lower()}"
    now = time.time()

    # Check in-memory cache first (fast path)
    cached_mem = _performance_cache.get(cache_key)
    if cached_mem and (now - cached_mem[0]) < _CACHE_TTL:
        return cached_mem[1]

    # Check DB cache (survives restarts)
    stmt = sa_select(CacheEntry).where(CacheEntry.key == cache_key)
    cached_db = (await db.execute(stmt)).scalar_one_or_none()
    if cached_db and cached_db.expires_at > datetime.utcnow():
        data = json.loads(cached_db.value)
        response = PerformanceResponse(
            period=data["period"],
            start_date=date.fromisoformat(data["start_date"]),
            data=[PerformanceDataPoint(**dp) for dp in data["data"]],
        )
        _performance_cache[cache_key] = (now, response)
        return response

    # Load all transactions
    stmt = select(Transaction).order_by(Transaction.date.asc())
    result = await db.execute(stmt)
    txs = list(result.scalars().all())

    tx_dicts = [
        {
            "symbol": t.symbol,
            "date": t.date,
            "quantity": float(t.quantity),
            "total_eur": float(t.total_eur),
            "transaction_type": t.transaction_type.value,
            "currency": t.currency,
            "notes": t.notes or "",
        }
        for t in txs
    ]

    # Load holdings for currency info and to detect missing transactions
    h_result = await db.execute(select(Holding))
    holdings = list(h_result.scalars().all())
    h_dicts = [{"symbol": h.symbol, "currency": h.currency} for h in holdings]

    # Synthesize opening balance transactions for holdings whose transaction
    # quantities don't account for the full current position (e.g., ESPP
    # shares loaded from a PDF statement without individual buy records).
    tx_qty_by_symbol: dict[str, float] = defaultdict(float)
    for t in tx_dicts:
        if t["transaction_type"] in ("buy", "espp_purchase", "deposit"):
            tx_qty_by_symbol[t["symbol"]] += t["quantity"]
        elif t["transaction_type"] in ("sell", "espp_sale", "withdrawal"):
            tx_qty_by_symbol[t["symbol"]] -= t["quantity"]

    earliest_date = min((t["date"] for t in tx_dicts), default=date.today())
    for h in holdings:
        holding_qty = float(h.total_quantity)
        tx_qty = tx_qty_by_symbol.get(h.symbol, 0.0)
        gap = holding_qty - tx_qty
        if gap > 0.01:  # significant gap — inject opening balance
            tx_dicts.append({
                "symbol": h.symbol,
                "date": earliest_date,
                "quantity": gap,
                "total_eur": float(h.avg_cost_basis_eur) * gap,
                "transaction_type": "buy",
                "currency": h.currency,
                "notes": "Opening balance: synthetic",
            })

    # Run blocking yfinance work in a thread
    response = await asyncio.to_thread(
        _compute_performance_sync, tx_dicts, h_dicts, cache_key.replace("performance-", "")
    )

    # Store in memory cache
    _performance_cache[cache_key] = (now, response)

    # Persist to DB cache (2-hour TTL)
    import uuid
    cache_data = json.dumps({
        "period": response.period,
        "start_date": response.start_date.isoformat(),
        "data": [
            {
                "date": dp.date.isoformat() if isinstance(dp.date, date) else dp.date,
                "portfolio_return_pct": dp.portfolio_return_pct,
                "sp500_return_pct": dp.sp500_return_pct,
                "portfolio_value_eur": dp.portfolio_value_eur,
            }
            for dp in response.data
        ],
    })
    expires = datetime.utcnow() + timedelta(hours=2)
    if cached_db:
        cached_db.value = cache_data
        cached_db.expires_at = expires
    else:
        db.add(CacheEntry(
            id=uuid.uuid4(),
            key=cache_key,
            value=cache_data,
            expires_at=expires,
        ))
    await db.flush()

    return response
