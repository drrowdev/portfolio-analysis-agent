"""Transaction history API."""

from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.transaction import Transaction, TransactionType
from app.schemas.transaction import TransactionCreate, TransactionRead

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.post("/", response_model=TransactionRead, status_code=201)
async def create_transaction(
    payload: TransactionCreate,
    db: AsyncSession = Depends(get_db),
) -> Transaction:
    """Create a new transaction record."""
    tx = Transaction(**payload.model_dump())
    db.add(tx)
    await db.commit()
    await db.refresh(tx)
    return tx


@router.delete("/{transaction_id}", status_code=204)
async def delete_transaction(
    transaction_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Delete a transaction by ID."""
    import uuid as _uuid

    stmt = select(Transaction).where(Transaction.id == _uuid.UUID(transaction_id))
    result = await db.execute(stmt)
    tx = result.scalar_one_or_none()
    if not tx:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Transaction not found")
    await db.delete(tx)
    await db.commit()


@router.patch("/{transaction_id}", response_model=TransactionRead)
async def patch_transaction(
    transaction_id: str,
    updates: dict,
    db: AsyncSession = Depends(get_db),
):
    """Partially update a transaction (fx_rate, currency, notes, etc.)."""
    import uuid as _uuid
    from fastapi import HTTPException
    from decimal import Decimal as D

    stmt = select(Transaction).where(Transaction.id == _uuid.UUID(transaction_id))
    result = await db.execute(stmt)
    tx = result.scalar_one_or_none()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")

    allowed_fields = {"fx_rate", "currency", "notes", "price_native", "total_native", "price_eur", "total_eur", "fees"}
    for key, value in updates.items():
        if key not in allowed_fields:
            continue
        if value is None:
            setattr(tx, key, None)
        elif key in ("fx_rate", "price_native", "total_native", "price_eur", "total_eur", "fees"):
            setattr(tx, key, D(str(value)))
        else:
            setattr(tx, key, value)

    await db.commit()
    await db.refresh(tx)
    return tx


@router.get("/", response_model=list[TransactionRead])
async def list_transactions(
    account_id: Optional[str] = Query(None, description="Filter by account ID"),
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
    transaction_type: Optional[TransactionType] = Query(None, description="Filter by type"),
    start_date: Optional[date] = Query(None, description="Start date (inclusive)"),
    end_date: Optional[date] = Query(None, description="End date (inclusive)"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[TransactionRead]:
    """List transactions with optional filtering."""
    stmt = select(Transaction).order_by(Transaction.date.desc(), Transaction.created_at.desc())

    if account_id:
        stmt = stmt.where(Transaction.account_id == account_id)
    if symbol:
        stmt = stmt.where(Transaction.symbol == symbol)
    if transaction_type:
        stmt = stmt.where(Transaction.transaction_type == transaction_type)
    if start_date:
        stmt = stmt.where(Transaction.date >= start_date)
    if end_date:
        stmt = stmt.where(Transaction.date <= end_date)

    stmt = stmt.offset(offset).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/count")
async def count_transactions(
    account_id: Optional[str] = Query(None),
    symbol: Optional[str] = Query(None),
    transaction_type: Optional[TransactionType] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return total count of transactions matching filters."""
    stmt = select(func.count(Transaction.id))

    if account_id:
        stmt = stmt.where(Transaction.account_id == account_id)
    if symbol:
        stmt = stmt.where(Transaction.symbol == symbol)
    if transaction_type:
        stmt = stmt.where(Transaction.transaction_type == transaction_type)
    if start_date:
        stmt = stmt.where(Transaction.date >= start_date)
    if end_date:
        stmt = stmt.where(Transaction.date <= end_date)

    result = await db.execute(stmt)
    return {"count": result.scalar_one()}


@router.get("/symbols")
async def list_transaction_symbols(
    db: AsyncSession = Depends(get_db),
) -> list[str]:
    """Return distinct symbols that have transactions."""
    stmt = select(Transaction.symbol).distinct().order_by(Transaction.symbol)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/realized-gains")
async def get_realized_gains(
    year: int = Query(default=None, description="Year to compute gains for (default: current year)"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Compute realized gains/losses from sell transactions using average cost basis.

    For each sell, the gain is: sell_total_eur - (avg_cost_per_share * quantity_sold)
    Average cost is computed from all buys for that symbol prior to the sell date.
    """
    import datetime

    if year is None:
        year = datetime.date.today().year

    start = date(year, 1, 1)
    end = date(year, 12, 31)

    # Get all sell transactions for the year
    sell_types = [TransactionType.sell, TransactionType.espp_sale]
    sell_stmt = (
        select(Transaction)
        .where(Transaction.transaction_type.in_(sell_types))
        .where(Transaction.date >= start)
        .where(Transaction.date <= end)
        .order_by(Transaction.date)
    )
    sell_result = await db.execute(sell_stmt)
    sells = list(sell_result.scalars().all())

    if not sells:
        return {
            "year": year,
            "total_realized_eur": 0.0,
            "total_gains_eur": 0.0,
            "total_losses_eur": 0.0,
            "trades": [],
        }

    # Get all buy transactions (to compute cost basis)
    buy_types = [TransactionType.buy, TransactionType.espp_purchase]
    buy_stmt = (
        select(Transaction)
        .where(Transaction.transaction_type.in_(buy_types))
        .order_by(Transaction.date)
    )
    buy_result = await db.execute(buy_stmt)
    buys = list(buy_result.scalars().all())

    # Build per-symbol buy ledger (FIFO)
    from collections import defaultdict

    buy_lots: dict[str, list[tuple[Decimal, Decimal]]] = defaultdict(list)  # symbol -> [(qty, price_eur)]
    for b in buys:
        if b.quantity and b.price_eur:
            buy_lots[b.symbol].append([b.quantity, b.price_eur])

    # Process sells using FIFO
    trades = []
    total_gains = Decimal("0")
    total_losses = Decimal("0")

    for s in sells:
        qty_to_sell = s.quantity or Decimal("0")
        proceeds = s.total_eur or Decimal("0")
        cost_basis = Decimal("0")
        lots = buy_lots.get(s.symbol, [])

        remaining = qty_to_sell
        while remaining > 0 and lots:
            lot_qty, lot_price = lots[0]
            if lot_qty <= remaining:
                cost_basis += lot_qty * lot_price
                remaining -= lot_qty
                lots.pop(0)
            else:
                cost_basis += remaining * lot_price
                lots[0] = [lot_qty - remaining, lot_price]
                remaining = Decimal("0")

        gain = proceeds - cost_basis - (s.fees or Decimal("0"))

        if gain >= 0:
            total_gains += gain
        else:
            total_losses += gain

        trades.append({
            "date": s.date.isoformat(),
            "symbol": s.symbol,
            "quantity": float(qty_to_sell),
            "proceeds_eur": float(proceeds),
            "cost_basis_eur": float(cost_basis),
            "fees_eur": float(s.fees or 0),
            "realized_gain_eur": float(gain),
        })

    return {
        "year": year,
        "total_realized_eur": float(total_gains + total_losses),
        "total_gains_eur": float(total_gains),
        "total_losses_eur": float(total_losses),
        "trade_count": len(trades),
        "trades": trades,
    }


@router.get("/dividends")
async def get_dividends(
    year: int = Query(default=None, description="Year to compute dividends for (default: current year)"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Aggregate dividend income by symbol for the given year."""
    import datetime

    if year is None:
        year = datetime.date.today().year

    start = date(year, 1, 1)
    end = date(year, 12, 31)

    stmt = (
        select(Transaction)
        .where(Transaction.transaction_type == TransactionType.dividend)
        .where(Transaction.date >= start)
        .where(Transaction.date <= end)
        .order_by(Transaction.date)
    )
    result = await db.execute(stmt)
    dividends = list(result.scalars().all())

    by_symbol: dict[str, dict] = {}
    total = Decimal("0")

    for d in dividends:
        amount = d.total_eur or Decimal("0")
        total += amount
        if d.symbol not in by_symbol:
            by_symbol[d.symbol] = {
                "symbol": d.symbol,
                "instrument_name": d.instrument_name,
                "total_eur": Decimal("0"),
                "payments": 0,
                "last_payment": None,
            }
        by_symbol[d.symbol]["total_eur"] += amount
        by_symbol[d.symbol]["payments"] += 1
        by_symbol[d.symbol]["last_payment"] = d.date.isoformat()

    symbols_list = sorted(by_symbol.values(), key=lambda x: x["total_eur"], reverse=True)
    for s in symbols_list:
        s["total_eur"] = float(s["total_eur"])

    return {
        "year": year,
        "total_dividends_eur": float(total),
        "payment_count": len(dividends),
        "by_symbol": symbols_list,
    }


@router.post("/dividends/check")
async def trigger_dividend_check(
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Manually trigger a check for new dividend payments across all holdings."""
    from app.services.dividend_detector import check_dividends

    created = await check_dividends(db)
    return {
        "new_dividends_created": created,
        "message": f"Found and recorded {created} new dividend payment(s)" if created else "No new dividends detected",
    }


@router.get("/tax-calculation")
async def compute_tax_calculation(
    symbol: str = Query(..., description="Symbol that was sold"),
    quantity: Decimal = Query(..., description="Number of shares sold"),
    sell_price_eur: Decimal = Query(..., description="Sale price per share in EUR"),
    sell_date: date = Query(..., description="Date of the sale"),
    fees_eur: Decimal = Query(Decimal("0"), description="Fees in EUR"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Compute Finnish capital gains tax (ennakkoveroilmoitus) info for a sell.

    Finnish tax rules:
    - Capital gains tax: 30% on gains ≤ €30,000/year, 34% on gains > €30,000
    - Hankintameno-olettama (deemed acquisition cost):
      - 20% of sale proceeds if held < 10 years
      - 40% of sale proceeds if held ≥ 10 years
    - Taxpayer can choose whichever method gives a lower gain
    """
    from collections import defaultdict
    from datetime import timedelta

    # 1. Fetch all buy/ESPP purchase lots for this symbol (FIFO order)
    buy_types = [TransactionType.buy, TransactionType.espp_purchase]
    buy_stmt = (
        select(Transaction)
        .where(Transaction.symbol == symbol)
        .where(Transaction.transaction_type.in_(buy_types))
        .order_by(Transaction.date)
    )
    buy_result = await db.execute(buy_stmt)
    buys = list(buy_result.scalars().all())

    # 2. Fetch all prior sells for this symbol (to consume lots already sold)
    sell_types = [TransactionType.sell, TransactionType.espp_sale]
    prior_sell_stmt = (
        select(Transaction)
        .where(Transaction.symbol == symbol)
        .where(Transaction.transaction_type.in_(sell_types))
        .where(Transaction.date <= sell_date)
        .order_by(Transaction.date)
    )
    prior_sell_result = await db.execute(prior_sell_stmt)
    prior_sells = list(prior_sell_result.scalars().all())

    # Build FIFO lot queue: [(qty_remaining, price_eur, purchase_date)]
    lots: list[list] = []
    for b in buys:
        if b.quantity and b.price_eur:
            lots.append([b.quantity, b.price_eur, b.date])

    # Consume lots for all prior sells EXCEPT the current one
    # (the current sell is the one matching our parameters)
    fx_rate = None
    for s in prior_sells:
        # Skip if this is the sell we're calculating for
        if (
            s.quantity == quantity
            and s.date == sell_date
            and abs(float(s.price_eur or 0) - float(sell_price_eur)) < 0.01
        ):
            # Capture FX rate from the matching sell transaction
            fx_rate = float(s.fx_rate) if s.fx_rate else None
            continue

        remaining = s.quantity or Decimal("0")
        while remaining > 0 and lots:
            lot_qty = lots[0][0]
            if lot_qty <= remaining:
                remaining -= lot_qty
                lots.pop(0)
            else:
                lots[0][0] = lot_qty - remaining
                remaining = Decimal("0")

    # If FX rate not on transaction, look it up from fx_rates table or live
    if fx_rate is None:
        from app.models.market_data import FxRate
        fx_stmt = (
            select(FxRate)
            .where(FxRate.pair == "EURUSD")
            .where(FxRate.date <= sell_date)
            .order_by(FxRate.date.desc())
            .limit(1)
        )
        fx_result = await db.execute(fx_stmt)
        fx_record = fx_result.scalar_one_or_none()
        if fx_record:
            fx_rate = float(fx_record.rate)
        else:
            # Fallback to live rate
            from app.services.market_data import get_fx_rate
            live_rate = await get_fx_rate("EURUSD")
            if live_rate:
                fx_rate = float(live_rate)

    # 3. Compute FIFO cost basis for this sell
    proceeds = quantity * sell_price_eur
    remaining_to_sell = quantity
    consumed_lots = []
    total_fifo_cost = Decimal("0")

    while remaining_to_sell > 0 and lots:
        lot_qty, lot_price, lot_date = lots[0]
        holding_days = (sell_date - lot_date).days
        holding_years = holding_days / 365.25

        if lot_qty <= remaining_to_sell:
            lot_cost = lot_qty * lot_price
            total_fifo_cost += lot_cost
            consumed_lots.append({
                "purchase_date": lot_date.isoformat(),
                "quantity": float(lot_qty),
                "cost_per_share_eur": float(lot_price),
                "lot_cost_eur": float(lot_cost),
                "holding_days": holding_days,
                "holding_years": round(holding_years, 1),
                "over_10_years": holding_years >= 10,
            })
            remaining_to_sell -= lot_qty
            lots.pop(0)
        else:
            lot_cost = remaining_to_sell * lot_price
            total_fifo_cost += lot_cost
            consumed_lots.append({
                "purchase_date": lot_date.isoformat(),
                "quantity": float(remaining_to_sell),
                "cost_per_share_eur": float(lot_price),
                "lot_cost_eur": float(lot_cost),
                "holding_days": holding_days,
                "holding_years": round(holding_years, 1),
                "over_10_years": holding_years >= 10,
            })
            lots[0][0] = lot_qty - remaining_to_sell
            remaining_to_sell = Decimal("0")

    # 4. Calculate hankintameno-olettama (deemed acquisition cost)
    # If any lot is over 10 years, 40%; otherwise 20%
    any_over_10 = any(lot["over_10_years"] for lot in consumed_lots)
    all_over_10 = all(lot["over_10_years"] for lot in consumed_lots) if consumed_lots else False

    # For mixed holding periods, compute deemed cost per lot
    deemed_cost_20 = proceeds * Decimal("0.20")
    deemed_cost_40 = proceeds * Decimal("0.40")

    # Determine which deemed rate is applicable
    # Conservative: use the lot-weighted approach
    # If all lots are over 10 years → 40%, otherwise → 20%
    deemed_rate = Decimal("0.40") if all_over_10 else Decimal("0.20")
    deemed_cost = proceeds * deemed_rate

    # 5. Choose the better method (lower gain = lower tax)
    gain_fifo = proceeds - total_fifo_cost - fees_eur
    gain_deemed = proceeds - deemed_cost  # fees not deductible with deemed cost

    use_deemed = gain_deemed < gain_fifo
    taxable_gain = min(gain_fifo, gain_deemed)

    # 6. Compute tax (30% up to €30k, 34% above)
    # Note: this is simplified — actual threshold is per-year across all gains
    if taxable_gain <= 0:
        tax_amount = Decimal("0")
        effective_rate = Decimal("0")
    elif taxable_gain <= 30000:
        tax_amount = taxable_gain * Decimal("0.30")
        effective_rate = Decimal("0.30")
    else:
        tax_amount = Decimal("30000") * Decimal("0.30") + (taxable_gain - Decimal("30000")) * Decimal("0.34")
        effective_rate = tax_amount / taxable_gain

    return {
        "symbol": symbol,
        "sell_date": sell_date.isoformat(),
        "quantity_sold": float(quantity),
        "sell_price_eur": float(sell_price_eur),
        "fees_eur": float(fees_eur),
        "fx_rate": fx_rate,

        # OmaVero form fields
        "omavero": {
            "luovutushinta": float(proceeds),           # Sale proceeds
            "hankintameno_todellinen": float(total_fifo_cost + fees_eur),  # Actual cost basis (FIFO + fees)
            "hankintameno_olettama": float(deemed_cost),  # Deemed acquisition cost
            "hankintameno_olettama_rate": f"{int(deemed_rate * 100)}%",
            "recommended_method": "hankintameno_olettama" if use_deemed else "todellinen_hankintameno",
            "luovutusvoitto": float(taxable_gain),      # Capital gain (using better method)
            "veron_maara": float(tax_amount),            # Tax amount
            "veroprosentti": f"{float(effective_rate * 100):.1f}%",  # Effective tax rate
        },

        # Comparison of methods
        "comparison": {
            "fifo_cost_basis_eur": float(total_fifo_cost),
            "fifo_gain_eur": float(gain_fifo),
            "deemed_cost_eur": float(deemed_cost),
            "deemed_gain_eur": float(gain_deemed),
            "better_method": "deemed" if use_deemed else "actual",
            "tax_savings_eur": float(abs(gain_fifo - gain_deemed) * (Decimal("0.30") if taxable_gain <= 30000 else Decimal("0.34"))),
        },

        # FIFO lot details
        "lots_consumed": consumed_lots,

        # Notes for user
        "notes": [
            "Hankintameno-olettama: 20% of sale price (held < 10 years) or 40% (held ≥ 10 years).",
            f"Your lots qualify for the {'40%' if all_over_10 else '20%'} deemed rate.",
            f"Using {'hankintameno-olettama' if use_deemed else 'actual FIFO cost basis'} results in lower tax.",
            "Capital gains tax: 30% on gains up to €30,000/year, 34% on amounts above.",
            "File ennakkoveroilmoitus in OmaVero within 2 months of the sale.",
            "This calculation covers this sale only — your total yearly gains may change the tax bracket.",
        ],
    }


@router.post("/fix-fx-rates/{symbol}")
async def fix_fx_rates(
    symbol: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Correct FX rates for all transactions of a symbol using historical ECB rates.

    Fetches actual EUR/USD rates from frankfurter.app (ECB reference rates) for each
    transaction date and recalculates price_eur and total_eur accordingly.
    """
    import httpx
    import asyncio
    from decimal import Decimal as D

    # Get all transactions for this symbol
    stmt = (
        select(Transaction)
        .where(Transaction.symbol == symbol)
        .where(Transaction.currency == "USD")
        .order_by(Transaction.date.asc())
    )
    result = await db.execute(stmt)
    transactions = list(result.scalars().all())

    if not transactions:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"No USD transactions found for {symbol}")

    # Get unique dates
    unique_dates = sorted(set(str(tx.date) for tx in transactions))

    # Fetch historical rates from ECB via frankfurter.app
    fx_rates: dict[str, float] = {}
    async with httpx.AsyncClient(timeout=30) as client:
        for date_str in unique_dates:
            url = f"https://api.frankfurter.app/{date_str}?from=USD&to=EUR"
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                usd_to_eur = data["rates"]["EUR"]
                eurusd = round(1.0 / usd_to_eur, 6)  # EUR/USD (1 EUR = X USD)
                fx_rates[date_str] = eurusd
            else:
                # API returns closest business day for weekends/holidays
                fx_rates[date_str] = None
            await asyncio.sleep(0.2)

    # Update each transaction
    updated = 0
    old_total_buy_eur = D("0")
    new_total_buy_eur = D("0")

    for tx in transactions:
        date_str = str(tx.date)
        rate = fx_rates.get(date_str)
        if rate is None:
            continue

        new_eurusd = D(str(rate))
        price_native = tx.price_native or D("0")
        total_native = tx.total_native or D("0")

        new_price_eur = (price_native / new_eurusd).quantize(D("0.0001"))
        new_total_eur = (total_native / new_eurusd).quantize(D("0.01"))

        if tx.transaction_type.value in ("buy", "espp_purchase"):
            old_total_buy_eur += tx.total_eur or D("0")
            new_total_buy_eur += new_total_eur

        tx.fx_rate = new_eurusd
        tx.price_eur = new_price_eur
        tx.total_eur = new_total_eur
        updated += 1

    await db.commit()

    return {
        "symbol": symbol,
        "transactions_updated": updated,
        "total_transactions": len(transactions),
        "dates_fetched": len(fx_rates),
        "dates_failed": sum(1 for v in fx_rates.values() if v is None),
        "old_total_buy_eur": float(old_total_buy_eur),
        "new_total_buy_eur": float(new_total_buy_eur),
        "cost_basis_change_eur": float(new_total_buy_eur - old_total_buy_eur),
        "sample_rates": {k: v for k, v in list(fx_rates.items())[:5]},
    }
