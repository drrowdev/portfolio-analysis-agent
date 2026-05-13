"""Automatic dividend detection using yfinance dividend history.

Checks all holdings for recent dividend payments and auto-creates
dividend transactions when new payments are detected.
"""

import logging
from datetime import date, timedelta
from decimal import Decimal

import yfinance as yf
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.holding import Holding
from app.models.transaction import Transaction, TransactionType
from app.services.market_data import _yf_symbol

logger = logging.getLogger(__name__)

# How far back to look for dividends (covers payment delay after ex-date)
LOOKBACK_DAYS = 30


async def check_dividends(session: AsyncSession) -> int:
    """Check all holdings for new dividend payments and create transactions.

    Returns the number of new dividend transactions created.
    """
    # Get all holdings with positive quantity
    result = await session.execute(
        select(Holding).where(Holding.total_quantity > 0)
    )
    holdings = list(result.scalars().all())

    if not holdings:
        return 0

    created = 0
    cutoff = date.today() - timedelta(days=LOOKBACK_DAYS)

    for holding in holdings:
        try:
            new_divs = await _check_holding_dividends(session, holding, cutoff)
            created += new_divs
        except Exception:
            logger.exception(
                "Failed to check dividends for %s", holding.symbol
            )

    return created


async def _check_holding_dividends(
    session: AsyncSession,
    holding: Holding,
    cutoff: date,
) -> int:
    """Check a single holding for new dividends since cutoff date.

    Returns number of new transactions created.
    """
    yf_symbol = _yf_symbol(holding.symbol)
    ticker = yf.Ticker(yf_symbol)

    # Get dividend history
    dividends = ticker.dividends
    if dividends.empty:
        return 0

    created = 0
    today = date.today()

    for div_date_ts, amount_per_share in dividends.items():
        div_date = div_date_ts.date()

        # Only look at dividends within our window and not in the future
        if div_date < cutoff or div_date > today:
            continue

        if amount_per_share <= 0:
            continue

        # Check if we already have this dividend recorded (deduplication)
        existing = await session.execute(
            select(Transaction).where(
                and_(
                    Transaction.symbol == holding.symbol,
                    Transaction.transaction_type == TransactionType.dividend,
                    Transaction.date == div_date,
                    Transaction.account_id == holding.account_id,
                )
            )
        )
        if existing.scalars().first() is not None:
            continue

        # Calculate total dividend
        quantity = holding.total_quantity
        amount_per_share_dec = Decimal(str(amount_per_share))
        total_native = amount_per_share_dec * quantity

        # For EUR-denominated holdings, native = EUR
        # For non-EUR, we'd need FX conversion (most Nordic stocks are EUR)
        currency = holding.currency
        if currency == "EUR":
            total_eur = total_native
            fx_rate = None
        else:
            # Attempt FX conversion for non-EUR dividends
            from app.services.market_data import get_fx_rate

            rate = await get_fx_rate(f"{currency}EUR")
            if rate:
                total_eur = total_native * rate
                fx_rate = rate
            else:
                total_eur = total_native
                fx_rate = None
                logger.warning(
                    "Could not get FX rate for %s, using 1:1 for %s dividend",
                    currency,
                    holding.symbol,
                )

        # Create the dividend transaction
        transaction = Transaction(
            account_id=holding.account_id,
            symbol=holding.symbol,
            isin=holding.isin,
            instrument_name=holding.instrument_name,
            currency=currency,
            transaction_type=TransactionType.dividend,
            date=div_date,
            quantity=quantity,
            price_native=amount_per_share_dec,
            price_eur=amount_per_share_dec if currency == "EUR" else (amount_per_share_dec * fx_rate if fx_rate else amount_per_share_dec),
            total_native=total_native,
            total_eur=total_eur,
            fx_rate=fx_rate,
            fees=Decimal("0"),
            notes="Auto-detected from yfinance dividend data",
        )
        session.add(transaction)
        created += 1

        logger.info(
            "Auto-created dividend: %s paid %.4f/share × %s = %.2f EUR on %s",
            holding.symbol,
            amount_per_share,
            quantity,
            total_eur,
            div_date,
        )

    return created
