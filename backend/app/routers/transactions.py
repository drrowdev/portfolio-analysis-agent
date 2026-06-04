"""Transaction history API."""

from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.account import Account
from app.models.transaction import Transaction, TransactionType
from app.schemas.transaction import TransactionCreate, TransactionRead
from app.services import capital_income as cap_income
from app.services import fx as fx_convert
from app.services import tax as tax_math

router = APIRouter(prefix="/transactions", tags=["transactions"])

ZERO = Decimal("0")


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


@router.get("/capital-income-summary")
async def capital_income_summary(
    year: int = Query(default=None, description="Tax year (default: current year)"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Year-to-date taxable capital income (gains + dividends) vs the €30k bracket.

    Computed directly from stored transactions — no saved tax calculations
    required. Excludes OST (``deferred``) accounts entirely (taxed only on
    withdrawal); counts listed-share dividends at 85 % (15 % tax-free). Capital
    gains use the per-lot best-of hankintameno-olettama engine.
    """
    import datetime

    if year is None:
        year = datetime.date.today().year

    # Account tax treatment lookup.
    acc_result = await db.execute(select(Account))
    treatment_by_id = {str(a.id): a.tax_treatment.value for a in acc_result.scalars().all()}

    # All gain/dividend-relevant transactions (all years — gains need full FIFO history).
    relevant = [
        TransactionType.buy,
        TransactionType.espp_purchase,
        TransactionType.sell,
        TransactionType.espp_sale,
        TransactionType.dividend,
    ]
    tx_result = await db.execute(
        select(Transaction)
        .where(Transaction.transaction_type.in_(relevant))
        .order_by(Transaction.date)
    )
    rows = list(tx_result.scalars().all())

    txns = [
        cap_income.IncomeTxn(
            account_id=str(t.account_id),
            tax_treatment=treatment_by_id.get(str(t.account_id), "standard"),
            symbol=t.symbol,
            txn_type=t.transaction_type.value,
            date=t.date,
            quantity=t.quantity or Decimal("0"),
            price_eur=t.price_eur or Decimal("0"),
            total_eur=t.total_eur or Decimal("0"),
            fees=t.fees or Decimal("0"),
        )
        for t in rows
    ]

    s = cap_income.compute_capital_income(txns, year)

    return {
        "year": s.year,
        "taxable_gains_eur": float(s.taxable_gains_eur),
        "gross_dividends_eur": float(s.gross_dividends_eur),
        "taxable_dividends_eur": float(s.taxable_dividends_eur),
        "dividend_taxable_fraction": float(cap_income.LISTED_DIVIDEND_TAXABLE_FRACTION),
        "combined_taxable_eur": float(s.combined_taxable_eur),
        "bracket_threshold_eur": float(s.bracket_threshold_eur),
        "remaining_at_low_rate_eur": float(s.remaining_at_low_rate_eur),
        "amount_over_threshold_eur": float(s.amount_over_threshold_eur),
        "estimated_tax_eur": float(s.estimated_tax_eur),
        "effective_rate": float(s.effective_rate),
        "low_rate": float(s.low_rate),
        "high_rate": float(s.high_rate),
        "sale_count": s.sale_count,
        "dividend_payment_count": s.dividend_payment_count,
        "excluded_ost_dividends_eur": float(s.excluded_ost_dividends_eur),
        "excluded_ost_sale_count": s.excluded_ost_sale_count,
        "sales": [
            {
                "symbol": x.symbol,
                "sell_date": x.sell_date.isoformat(),
                "quantity": float(x.quantity),
                "proceeds_eur": float(x.proceeds_eur),
                "gain_eur": float(x.gain_eur),
            }
            for x in s.sales
        ],
        "dividends": [
            {
                "symbol": d.symbol,
                "gross_eur": float(d.gross_eur),
                "taxable_eur": float(d.taxable_eur),
                "payments": d.payments,
            }
            for d in s.dividends
        ],
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


async def _year_capital_income(
    db: AsyncSession, year: int, before_date: Optional[date] = None
) -> cap_income.CapitalIncomeSummary:
    """Compute the tracked taxable capital-income summary for ``year``.

    Same data set as ``GET /capital-income-summary`` (all gain/dividend-relevant
    transactions across all years for full FIFO history; OST excluded inside the
    service). When ``before_date`` is given, only income realised strictly before
    that date is counted — used to position a later sale's gain on the per-year
    30 %/34 % bracket.
    """
    acc_result = await db.execute(select(Account))
    treatment_by_id = {str(a.id): a.tax_treatment.value for a in acc_result.scalars().all()}

    relevant = [
        TransactionType.buy,
        TransactionType.espp_purchase,
        TransactionType.sell,
        TransactionType.espp_sale,
        TransactionType.dividend,
    ]
    tx_result = await db.execute(
        select(Transaction)
        .where(Transaction.transaction_type.in_(relevant))
        .order_by(Transaction.date)
    )
    rows = list(tx_result.scalars().all())
    txns = [
        cap_income.IncomeTxn(
            account_id=str(t.account_id),
            tax_treatment=treatment_by_id.get(str(t.account_id), "standard"),
            symbol=t.symbol,
            txn_type=t.transaction_type.value,
            date=t.date,
            quantity=t.quantity or Decimal("0"),
            price_eur=t.price_eur or Decimal("0"),
            total_eur=t.total_eur or Decimal("0"),
            fees=t.fees or Decimal("0"),
        )
        for t in rows
    ]
    return cap_income.compute_capital_income(txns, year, before_date)


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

    # 3. Compute FIFO cost basis for this sell. Each consumed lot becomes a
    #    TaxLot input for the (DB-free, unit-tested) capital-gains math.
    remaining_to_sell = quantity
    consumed_lots: list[dict] = []
    lot_inputs: list[tax_math.TaxLot] = []

    while remaining_to_sell > 0 and lots:
        lot_qty, lot_price, lot_date = lots[0]
        holding_days = (sell_date - lot_date).days
        holding_years = holding_days / 365.25
        # ≥10-year boundary is calendar-based (TVL hankintameno-olettama):
        # 40 % applies once the sale date reaches the 10-year anniversary.
        over_10 = tax_math.held_at_least_10_years(lot_date, sell_date)

        take = lot_qty if lot_qty <= remaining_to_sell else remaining_to_sell
        lot_cost = take * lot_price
        consumed_lots.append({
            "purchase_date": lot_date.isoformat(),
            "quantity": float(take),
            "cost_per_share_eur": float(lot_price),
            "lot_cost_eur": float(lot_cost),
            "holding_days": holding_days,
            "holding_years": round(holding_years, 1),
            "over_10_years": over_10,
        })
        lot_inputs.append(
            tax_math.TaxLot(quantity=take, cost_per_share_eur=lot_price, over_10_years=over_10)
        )

        if lot_qty <= remaining_to_sell:
            remaining_to_sell -= lot_qty
            lots.pop(0)
        else:
            lots[0][0] = lot_qty - remaining_to_sell
            remaining_to_sell = Decimal("0")

    # 4-6. Per-lot hankintameno-olettama, method selection, and tax.
    result = tax_math.compute(lot_inputs, sell_price_eur, fees_eur, quantity)

    # --- Automatic 30 %/34 % bracket positioning -------------------------------
    # Position this sale's gain on the per-YEAR €30k bracket using the user's
    # capital income realised EARLIER in the same calendar year (realized gains +
    # 85% dividends, OST excluded) — i.e. income with a date strictly before this
    # sale. Chronological stacking means the first sales of the year fill the 30 %
    # band first; later sales cross into 34 %. A hypothetical (unsaved) sale is
    # naturally excluded too, since nothing is dated on/after it.
    year = sell_date.year
    prior_summary = await _year_capital_income(db, year, before_date=sell_date)
    gain = result.optimum_gain_eur
    prior_income = prior_summary.combined_taxable_eur

    # Bracket-aware tax for this sale (marginal stacking on prior YTD income).
    tax_eur, effective_rate = tax_math.capital_gains_tax(gain, prior_income)

    threshold = tax_math.BRACKET_THRESHOLD
    # Split this sale's gain into the 30 %- and 34 %-taxed portions, consistent
    # with capital_gains_tax(): income below 0 is shielded (loss carry within the
    # year), 0–30k at 30 %, above 30k at 34 %.
    _start = prior_income
    _end = prior_income + gain
    _t_start = max(_start, ZERO)
    _t_end = max(_end, ZERO)
    low_part = max(ZERO, min(_t_end, threshold) - min(_t_start, threshold))
    high_part = max(ZERO, _t_end - max(_t_start, threshold))
    headroom_before_sale = max(ZERO, threshold - max(prior_income, ZERO))
    applies_high_rate = high_part > 0
    crosses_threshold = low_part > 0 and high_part > 0
    fully_above_threshold = applies_high_rate and low_part == 0

    bracket = {
        "year": year,
        "prior_ytd_income_eur": float(prior_income),
        "threshold_eur": float(threshold),
        "headroom_before_sale_eur": float(headroom_before_sale),
        "this_sale_gain_eur": float(gain),
        "amount_taxed_at_low_eur": float(low_part),
        "amount_taxed_at_high_eur": float(high_part),
        "low_rate": float(tax_math.LOW_TAX_RATE),
        "high_rate": float(tax_math.HIGH_TAX_RATE),
        "applies_high_rate": applies_high_rate,
        "crosses_threshold": crosses_threshold,
        "fully_above_threshold": fully_above_threshold,
    }

    # Annotate each consumed lot with the rate/method actually applied to it.
    for lot_out, lot_res in zip(consumed_lots, result.lots):
        lot_out["applied_deemed_rate"] = f"{int(lot_res.applied_rate * 100)}%"
        lot_out["method"] = lot_res.method

    method_label = {
        "hankintameno_olettama": f"hankintameno-olettama ({result.rate_label})",
        "todellinen_hankintameno": "todellinen hankintameno (FIFO)",
        "yhdistelma": "eräkohtainen yhdistelmä (osa olettama, osa todellinen)",
    }[result.recommended_method]

    if fully_above_threshold:
        bracket_note = (
            f"⚠️ Vuoden {year} aiemmat seuratut pääomatulot "
            f"({float(prior_income):.2f} €) ylittävät jo 30 000 € rajan, joten "
            f"tämän myynnin koko luovutusvoitto ({float(gain):.2f} €) verotetaan "
            f"34 %:n mukaan."
        )
    elif crosses_threshold:
        bracket_note = (
            f"⚠️ Tämä myynti ylittää 30 000 € pääomatulorajan vuonna {year}: "
            f"{float(low_part):.2f} € verotetaan 30 % ja {float(high_part):.2f} € "
            f"34 %:n mukaan (vuoden aiemmat seuratut pääomatulot "
            f"{float(prior_income):.2f} €)."
        )
    else:
        bracket_note = (
            f"Vuoden {year} aiemmat seuratut pääomatulot "
            f"({float(prior_income):.2f} €) on huomioitu: tämä myynti pysyy 30 %:n "
            f"portaassa (rajaan jäljellä {float(headroom_before_sale):.2f} €)."
        )

    notes = [
        "Hankintameno-olettama lasketaan eräkohtaisesti: 20 % myyntihinnasta "
        "(omistus < 10 v) tai 40 % (omistus ≥ 10 v).",
        f"Edullisin menetelmä tälle myynnille: {method_label}.",
        bracket_note,
        "Pääomatulovero: 30 % enintään 30 000 € pääomatuloista vuodessa, 34 % "
        "ylittävältä osalta. Laskelma huomioi tässä sovelluksessa seuratut "
        "pääomatulot (luovutusvoitot + 85 % osingoista, OST-tili pois lukien). "
        "Sovelluksen ulkopuoliset pääomatulot (vuokratulot, korot, "
        "listaamattomien yhtiöiden osingot ym.) lasketaan samaan 30 000 € "
        "rajaan, mutta eivät näy tässä.",
        "Pienten luovutusten verovapaus (TVL 48.6 §): jos verovuoden KAIKKIEN "
        "omaisuuden luovutusten yhteenlasketut myyntihinnat ovat enintään "
        "1 000 €, luovutusvoitto on verovapaa. Tämä laskelma ei näe muita "
        "vuoden myyntejä, joten tarkista raja itse.",
        "Maksa lisäennakko OmaVerossa: verovuoden myyntien verot voi maksaa "
        "ilman korkoseuraamuksia seuraavan vuoden tammikuun loppuun mennessä "
        "(esim. myynti 2026 → maksa viimeistään 31.1.2027). Myöhemmin "
        "maksettuna kertyy huojennettua viivästyskorkoa. Lisäennakon "
        "vähimmäismäärä on 170 €.",
    ]
    if result.shortfall_qty > 0:
        notes.insert(
            0,
            f"⚠️ VAROITUS: myydyistä {float(quantity):g} osakkeesta vain "
            f"{float(result.covered_qty):g} kpl löytyy ostotapahtumista. Puuttuvalle "
            f"{float(result.shortfall_qty):g} osakkeelle käytettiin 20 % "
            "hankintameno-olettamaa. Tarkista ostohistoria (ja aja tarvittaessa "
            "/transactions/fix-fx-rates/{symbol}) — todellinen hankintameno voi "
            "pienentää veroa.",
        )

    return {
        "symbol": symbol,
        "sell_date": sell_date.isoformat(),
        "quantity_sold": float(quantity),
        "sell_price_eur": float(sell_price_eur),
        "fees_eur": float(fees_eur),
        "fx_rate": fx_rate,

        # OmaVero form fields
        "omavero": {
            "luovutushinta": float(result.proceeds_eur),  # Sale proceeds
            "hankintameno_todellinen": float(result.actual_cost_total_eur + fees_eur),
            "hankintameno_olettama": float(result.deemed_cost_total_eur),  # per-lot rates
            "hankintameno_olettama_rate": result.rate_label,
            "hankintameno_kaytetty": float(result.used_deduction_eur),  # effective deduction
            "recommended_method": result.recommended_method,
            "luovutusvoitto": float(result.optimum_gain_eur),
            "veron_maara": float(tax_eur),
            "veroprosentti": f"{float(effective_rate * 100):.1f}%",
        },

        # Automatic 30%/34% bracket positioning for the year
        "bracket": bracket,

        # Comparison of single-method strategies
        "comparison": {
            "fifo_cost_basis_eur": float(result.actual_cost_total_eur),
            "fifo_gain_eur": float(result.all_actual_gain_eur),
            "deemed_cost_eur": float(result.deemed_cost_total_eur),
            "deemed_gain_eur": float(result.all_deemed_gain_eur),
            "better_method": "deemed" if result.all_deemed_gain_eur < result.all_actual_gain_eur else "actual",
            "tax_savings_eur": float(
                max(
                    ZERO,
                    tax_math.capital_gains_tax(result.all_actual_gain_eur, prior_income)[0]
                    - tax_eur,
                )
            ),
        },

        # Coverage of the sold quantity by recorded acquisition lots
        "coverage": {
            "quantity_sold": float(quantity),
            "quantity_covered": float(result.covered_qty),
            "shortfall_qty": float(result.shortfall_qty),
        },

        # FIFO lot details
        "lots_consumed": consumed_lots,

        # Notes for user
        "notes": notes,
    }


@router.post("/fix-fx-rates/{symbol}")
async def fix_fx_rates(
    symbol: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Correct FX rates for all transactions of a symbol using historical ECB rates.

    Fetches actual EUR/USD rates from frankfurter.app (ECB reference rates) for each
    transaction date and recalculates price_eur and total_eur accordingly.

    This is the manual re-run of the same conversion that now runs automatically
    on import (see ``app.services.fx`` and the Fidelity upload route).
    """
    from fastapi import HTTPException

    summary = await fx_convert.convert_symbol_to_eur(db, symbol)
    if summary["total_transactions"] == 0:
        raise HTTPException(status_code=404, detail=f"No USD transactions found for {symbol}")
    await db.commit()
    return summary
