"""USD->EUR FX conversion for imported transactions.

Fidelity ESPP statements are USD-native, so on import the transactions are
stored with ``price_eur``/``total_eur`` holding the raw USD figures (see
``routers/upload.py``). Finnish tax math needs EUR, so those rows must be
converted using the **historical ECB reference rate for each transaction's
own date** (not today's rate).

This module centralises that conversion so it can run automatically on upload
*and* be re-triggered manually via ``POST /transactions/fix-fx-rates/{symbol}``.

Network: ECB rates are fetched from frankfurter.app (free, no key). The
conversion mutates the ORM objects in the passed session but does **not**
commit — the caller owns the transaction boundary.
"""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.transaction import Transaction, TransactionType

logger = logging.getLogger(__name__)

_BUY_TYPES = (TransactionType.buy.value, TransactionType.espp_purchase.value)
_RATE_QUANT = Decimal("0.000001")
_PRICE_QUANT = Decimal("0.0001")
_TOTAL_QUANT = Decimal("0.01")


async def fetch_eurusd_rates(
    dates: list[str], *, client: httpx.AsyncClient | None = None
) -> dict[str, Decimal | None]:
    """Fetch EUR/USD (1 EUR = X USD) ECB reference rates for each date.

    Returns ``{date_str: Decimal | None}``; ``None`` marks a date the API
    could not resolve. frankfurter.app returns the closest prior business day
    for weekends/holidays, so a ``None`` generally means a transport error.
    """
    rates: dict[str, Decimal | None] = {}
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=30)
    try:
        for date_str in dates:
            try:
                resp = await client.get(
                    f"https://api.frankfurter.app/{date_str}?from=USD&to=EUR"
                )
                if resp.status_code == 200:
                    usd_to_eur = resp.json()["rates"]["EUR"]
                    rates[date_str] = (Decimal("1") / Decimal(str(usd_to_eur))).quantize(
                        _RATE_QUANT
                    )
                else:
                    rates[date_str] = None
            except (httpx.HTTPError, KeyError, ValueError, ArithmeticError) as exc:
                logger.warning("FX rate fetch failed for %s: %s", date_str, exc)
                rates[date_str] = None
            await asyncio.sleep(0.2)
    finally:
        if owns_client:
            await client.aclose()
    return rates


async def convert_symbol_to_eur(db: AsyncSession, symbol: str) -> dict:
    """Convert all USD transactions of ``symbol`` to EUR using ECB rates.

    Mutates ``price_eur``, ``total_eur`` and ``fx_rate`` on each row from the
    raw native (USD) values. Does not commit. Returns a summary dict.
    """
    stmt = (
        select(Transaction)
        .where(Transaction.symbol == symbol)
        .where(Transaction.currency == "USD")
        .order_by(Transaction.date.asc())
    )
    transactions = list((await db.execute(stmt)).scalars().all())
    if not transactions:
        return {
            "symbol": symbol,
            "transactions_updated": 0,
            "total_transactions": 0,
            "dates_fetched": 0,
            "dates_failed": 0,
            "old_total_buy_eur": 0.0,
            "new_total_buy_eur": 0.0,
            "cost_basis_change_eur": 0.0,
            "sample_rates": {},
        }

    unique_dates = sorted({str(tx.date) for tx in transactions})
    fx_rates = await fetch_eurusd_rates(unique_dates)

    updated = 0
    old_total_buy_eur = Decimal("0")
    new_total_buy_eur = Decimal("0")

    for tx in transactions:
        rate = fx_rates.get(str(tx.date))
        if rate is None or rate == 0:
            continue

        price_native = tx.price_native or Decimal("0")
        total_native = tx.total_native or Decimal("0")
        new_price_eur = (price_native / rate).quantize(_PRICE_QUANT)
        new_total_eur = (total_native / rate).quantize(_TOTAL_QUANT)

        if tx.transaction_type.value in _BUY_TYPES:
            old_total_buy_eur += tx.total_eur or Decimal("0")
            new_total_buy_eur += new_total_eur

        tx.fx_rate = rate
        tx.price_eur = new_price_eur
        tx.total_eur = new_total_eur
        updated += 1

    return {
        "symbol": symbol,
        "transactions_updated": updated,
        "total_transactions": len(transactions),
        "dates_fetched": len(fx_rates),
        "dates_failed": sum(1 for v in fx_rates.values() if v is None),
        "old_total_buy_eur": float(old_total_buy_eur),
        "new_total_buy_eur": float(new_total_buy_eur),
        "cost_basis_change_eur": float(new_total_buy_eur - old_total_buy_eur),
        "sample_rates": {k: (float(v) if v is not None else None) for k, v in list(fx_rates.items())[:5]},
    }
