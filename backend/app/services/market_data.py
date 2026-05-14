"""Market data fetching via yfinance and FX rate lookups."""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

import yfinance as yf
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.holding import Holding
from app.models.market_data import FxRate, MarketPrice
from app.services import symbol_metadata


def _yf_symbol(symbol: str) -> str:
    """Convert portfolio ticker to yfinance-compatible symbol."""
    return symbol_metadata.yahoo_symbol(symbol)


from dataclasses import dataclass


@dataclass
class PriceInfo:
    last_price: Optional[Decimal]
    previous_close: Optional[Decimal]
    market_state: Optional[str]           # REGULAR, PRE, POST, CLOSED, PREPRE, POSTPOST
    extended_price: Optional[Decimal]     # pre- or post-market price
    extended_change_pct: Optional[Decimal] # pre- or post-market change %


async def get_current_price(symbol: str) -> PriceInfo:
    """Fetch the latest price, previous close, and extended hours data."""
    ticker = yf.Ticker(_yf_symbol(symbol))
    info = ticker.info

    # Use info dict for all prices — fast_info.previous_close can be stale/adjusted
    last_price = info.get("regularMarketPrice")
    prev_close = info.get("regularMarketPreviousClose")
    market_state = info.get("marketState")

    extended_price = None
    extended_change_pct = None

    # Try pre-market data first, then post-market.
    # Yahoo exposes post-market data even when state is PREPRE/CLOSED (from prior session),
    # and pre-market data once state is PRE.
    if market_state == "PRE":
        p = info.get("preMarketPrice")
        c = info.get("preMarketChangePercent")
        if p is not None:
            extended_price = Decimal(str(p))
        if c is not None:
            extended_change_pct = Decimal(str(c))

    # For POST/POSTPOST/PREPRE/CLOSED, show last available post-market data
    if extended_price is None and market_state in ("POST", "POSTPOST", "PREPRE", "CLOSED"):
        p = info.get("postMarketPrice")
        c = info.get("postMarketChangePercent")
        if p is not None:
            extended_price = Decimal(str(p))
        if c is not None:
            extended_change_pct = Decimal(str(c))

    return PriceInfo(
        last_price=Decimal(str(last_price)) if last_price is not None else None,
        previous_close=Decimal(str(prev_close)) if prev_close is not None else None,
        market_state=market_state,
        extended_price=extended_price,
        extended_change_pct=extended_change_pct,
    )


async def get_fx_rate(pair: str, target_date: Optional[date] = None) -> Optional[Decimal]:
    """Fetch the FX rate for a currency pair (e.g., 'EURUSD').

    If target_date is None, returns the latest rate.
    Otherwise returns the close rate on the requested date, or the
    most recent prior trading day's close if the date itself is not
    a trading day (weekend/holiday).
    """
    ticker = yf.Ticker(f"{pair}=X")
    if target_date is None:
        hist = ticker.history(period="5d")
        if hist.empty:
            return None
        return Decimal(str(hist["Close"].iloc[-1]))

    # Historical: fetch a window covering the target date, take the close
    # at or before target_date. yfinance's `end` is exclusive, so add a day.
    from datetime import timedelta
    start = target_date - timedelta(days=7)
    end = target_date + timedelta(days=1)
    hist = ticker.history(start=str(start), end=str(end))
    if hist.empty:
        return None
    # hist index is tz-aware DatetimeIndex; compare on date()
    on_or_before = [(idx, row["Close"]) for idx, row in hist.iterrows() if idx.date() <= target_date]
    if not on_or_before:
        return None
    _, close = on_or_before[-1]
    return Decimal(str(close))


async def get_historical_prices(
    symbol: str,
    start: date,
    end: date,
) -> list[dict]:
    """Fetch historical OHLCV data for a symbol."""
    ticker = yf.Ticker(symbol)
    hist = ticker.history(start=str(start), end=str(end))
    rows: list[dict] = []
    for idx, row in hist.iterrows():
        rows.append(
            {
                "date": idx.date(),
                "open": Decimal(str(row["Open"])),
                "high": Decimal(str(row["High"])),
                "low": Decimal(str(row["Low"])),
                "close": Decimal(str(row["Close"])),
                "volume": int(row["Volume"]),
            }
        )
    return rows


async def refresh_prices(symbols: list[str], db: AsyncSession) -> dict[str, PriceInfo]:
    """Fetch latest prices for a list of symbols and store in MarketPrice table.
    
    Returns dict of symbol -> PriceInfo.
    """
    import uuid

    prices: dict[str, PriceInfo] = {}
    today = date.today()

    for symbol in symbols:
        try:
            pi = await get_current_price(symbol)
            if pi.last_price is None:
                continue

            prices[symbol] = pi

            # Upsert into MarketPrice
            stmt = select(MarketPrice).where(
                MarketPrice.symbol == symbol,
                MarketPrice.date == today,
            )
            existing = (await db.execute(stmt)).scalar_one_or_none()

            if existing:
                existing.close = pi.last_price
                existing.high = pi.last_price
                existing.low = pi.last_price
                existing.open = pi.last_price
                existing.volume = 0
            else:
                mp = MarketPrice(
                    id=uuid.uuid4(),
                    symbol=symbol,
                    date=today,
                    open=pi.last_price,
                    high=pi.last_price,
                    low=pi.last_price,
                    close=pi.last_price,
                    volume=0,
                    currency="USD",  # default; adjusted below for EUR stocks
                )
                db.add(mp)

        except Exception:
            continue

    await db.flush()
    return prices


async def refresh_fx_rate(pair: str, db: AsyncSession) -> Optional[Decimal]:
    """Fetch latest FX rate and store in FxRate table."""
    import uuid

    rate = await get_fx_rate(pair)
    if rate is None:
        return None

    today = date.today()
    stmt = select(FxRate).where(FxRate.pair == pair, FxRate.date == today)
    existing = (await db.execute(stmt)).scalar_one_or_none()

    if existing:
        existing.rate = rate
    else:
        fx = FxRate(
            id=uuid.uuid4(),
            pair=pair,
            date=today,
            rate=rate,
        )
        db.add(fx)

    await db.flush()
    return rate


async def update_holdings_prices(db: AsyncSession) -> int:
    """Update all holdings with latest market prices and FX rates.

    Returns the number of holdings updated.
    """
    # Get EUR/USD rate
    eurusd_rate = await get_fx_rate("EURUSD")
    if eurusd_rate is None:
        eurusd_rate = Decimal("1.13")  # fallback (USD per 1 EUR)

    # Store the FX rate
    await refresh_fx_rate("EURUSD", db)

    # Get all holdings
    result = await db.execute(select(Holding))
    holdings = list(result.scalars().all())

    # Collect unique symbols
    symbols = list({h.symbol for h in holdings})
    prices = await refresh_prices(symbols, db)

    updated = 0
    for holding in holdings:
        price_data = prices.get(holding.symbol)
        if price_data is None:
            continue

        price = price_data.last_price
        prev_close = price_data.previous_close

        holding.current_price_native = price
        holding.last_price_update = datetime.utcnow()

        # Compute daily price change %
        if prev_close and prev_close > 0:
            holding.price_change_pct = (price - prev_close) / prev_close * 100
        else:
            holding.price_change_pct = None

        # Extended hours data
        holding.market_state = price_data.market_state
        holding.extended_hours_price = price_data.extended_price
        holding.extended_hours_change_pct = price_data.extended_change_pct

        if holding.currency == "USD":
            # EURUSD rate = USD per 1 EUR, so divide to get EUR
            holding.current_price_eur = price / eurusd_rate
        else:
            holding.current_price_eur = price

        value_eur = holding.total_quantity * holding.current_price_eur
        holding.current_value_eur = value_eur

        cost = holding.total_cost_eur or Decimal("0")
        pnl = value_eur - cost
        holding.unrealized_pnl_eur = pnl
        holding.unrealized_pnl_pct = (pnl / cost * 100) if cost else Decimal("0")

        updated += 1

    # Compute portfolio weights
    total_value = sum(
        h.current_value_eur for h in holdings if h.current_value_eur
    )
    if total_value:
        for holding in holdings:
            if holding.current_value_eur:
                holding.portfolio_weight_pct = (
                    holding.current_value_eur / total_value * 100
                )

    await db.flush()
    return updated
