"""Automatic dividend detection using yfinance dividend history.

Checks all holdings for recent dividend payments and auto-creates
dividend transactions when new payments are detected.
"""

import logging
from datetime import date
from decimal import Decimal

import yfinance as yf
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.holding import Holding
from app.models.transaction import Transaction, TransactionType
from app.services.dividend_logic import (
    dedup_window,
    recognition_decision,
)
from app.services.market_data import _yf_symbol

logger = logging.getLogger(__name__)


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
    today = date.today()

    for holding in holdings:
        try:
            new_divs = await _check_holding_dividends(session, holding, today)
            created += new_divs
        except Exception:
            logger.exception(
                "Failed to check dividends for %s", holding.symbol
            )

    return created


async def _check_holding_dividends(
    session: AsyncSession,
    holding: Holding,
    today: date,
) -> int:
    """Check a single holding for new, already-paid dividends.

    Returns number of new transactions created.
    """
    yf_symbol = _yf_symbol(holding.symbol)
    ticker = yf.Ticker(yf_symbol)

    # Get dividend history (indexed by ex-dividend date; no pay date available)
    dividends = ticker.dividends
    if dividends.empty:
        return 0

    created = 0

    for div_date_ts, amount_per_share in dividends.items():
        ex_date = div_date_ts.date()
        amount_per_share_dec = Decimal(str(amount_per_share))

        # Gate on the estimated pay date: skip non-positive amounts, ex-dates
        # outside the lookback window, and dividends not yet paid (declared but
        # whose estimated pay date is still in the future).
        pay_date = recognition_decision(ex_date, today, amount_per_share_dec)
        if pay_date is None:
            continue

        # Deduplicate against any existing dividend near the estimated pay date
        # (tolerant window absorbs the pay-date approximation and small date
        # differences against manually imported rows).
        win_start, win_end = dedup_window(pay_date)
        existing = await session.execute(
            select(Transaction).where(
                and_(
                    Transaction.symbol == holding.symbol,
                    Transaction.transaction_type == TransactionType.dividend,
                    Transaction.date >= win_start,
                    Transaction.date <= win_end,
                    Transaction.account_id == holding.account_id,
                )
            )
        )
        if existing.scalars().first() is not None:
            continue

        # Calculate total dividend
        quantity = holding.total_quantity
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

        # Create the dividend transaction. Quantity is stored as 0 to match the
        # convention of manually imported dividend rows (a dividend is income,
        # not a share movement); the per-share figure and share count are kept in
        # the notes for traceability. The transaction date is the estimated pay
        # date so the income lands in the correct (payment-year) tax bucket.
        transaction = Transaction(
            account_id=holding.account_id,
            symbol=holding.symbol,
            isin=holding.isin,
            instrument_name=holding.instrument_name,
            currency=currency,
            transaction_type=TransactionType.dividend,
            date=pay_date,
            quantity=Decimal("0"),
            price_native=total_native,
            price_eur=total_eur,
            total_native=total_native,
            total_eur=total_eur,
            fx_rate=fx_rate,
            fees=Decimal("0"),
            notes=(
                f"Auto-detected from yfinance "
                f"({amount_per_share_dec}/share × {quantity} sh, ex {ex_date})"
            ),
        )
        session.add(transaction)
        created += 1

        logger.info(
            "Auto-created dividend: %s paid %.4f/share × %s = %.2f EUR "
            "(ex %s, est. pay %s)",
            holding.symbol,
            amount_per_share,
            quantity,
            total_eur,
            ex_date,
            pay_date,
        )

    return created
