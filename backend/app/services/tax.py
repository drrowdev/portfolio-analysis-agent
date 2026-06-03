"""Finnish capital-gains (luovutusvoitto / ennakkovero) math.

Pure, database-free functions so the calculation can be unit-tested in
isolation. The router (``app/routers/transactions.py``) handles the FIFO lot
selection against the DB and then delegates the tax math to ``compute``.

Implements the Finnish rules:

- **Hankintameno-olettama (deemed acquisition cost)** is applied **per lot**
  based on each lot's own holding period:
    - 20% of that lot's sale proceeds if held < 10 years
    - 40% of that lot's sale proceeds if held >= 10 years
  This is the key correctness point: a single recent lot must NOT deny the
  40% rate to lots held for 10+ years.
- The taxpayer may deduct, **per lot**, whichever is larger — the actual
  acquisition cost (plus a pro-rata share of selling fees) or the deemed
  cost. The deemed cost requires no documentation; it is a fixed percentage
  of the sale price.
- Capital-income tax: 30% on gains up to EUR 30,000, 34% above. NOTE: the
  EUR 30,000 threshold is on the taxpayer's *total annual capital income*,
  not a single sale. This module applies it per-sale; callers must surface
  that caveat to the user.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

ZERO = Decimal("0")
RATE_UNDER_10 = Decimal("0.20")
RATE_OVER_10 = Decimal("0.40")
BRACKET_THRESHOLD = Decimal("30000")
LOW_TAX_RATE = Decimal("0.30")
HIGH_TAX_RATE = Decimal("0.34")
_EPS = Decimal("0.005")


def deemed_rate(over_10_years: bool) -> Decimal:
    """Hankintameno-olettama rate for a lot given its holding period."""
    return RATE_OVER_10 if over_10_years else RATE_UNDER_10


def capital_gains_tax(gain: Decimal) -> tuple[Decimal, Decimal]:
    """Return ``(tax, effective_rate)`` for a taxable gain.

    Per-sale 30k/34k bracket — callers must note the threshold is really a
    per-year, total-capital-income figure.
    """
    if gain <= 0:
        return ZERO, ZERO
    if gain <= BRACKET_THRESHOLD:
        return gain * LOW_TAX_RATE, LOW_TAX_RATE
    tax = BRACKET_THRESHOLD * LOW_TAX_RATE + (gain - BRACKET_THRESHOLD) * HIGH_TAX_RATE
    return tax, tax / gain


@dataclass
class TaxLot:
    """A FIFO-consumed lot feeding the capital-gains calculation."""

    quantity: Decimal
    cost_per_share_eur: Decimal
    over_10_years: bool


@dataclass
class LotResult:
    """Per-lot outcome — which method won and the resulting gain."""

    quantity: Decimal
    cost_per_share_eur: Decimal
    over_10_years: bool
    proceeds_eur: Decimal
    applied_rate: Decimal
    deemed_cost_eur: Decimal
    actual_cost_eur: Decimal  # includes the lot's allocated fee share
    method: str  # 'deemed' | 'actual'
    gain_eur: Decimal


@dataclass
class TaxResult:
    """Full capital-gains result for one sale."""

    proceeds_eur: Decimal
    actual_cost_total_eur: Decimal  # FIFO cost basis of covered lots (no fees)
    fees_eur: Decimal
    deemed_cost_total_eur: Decimal  # per-lot correct olettama rates
    all_actual_gain_eur: Decimal  # gain if every lot used actual cost
    all_deemed_gain_eur: Decimal  # gain if every lot used deemed cost
    optimum_gain_eur: Decimal  # per-lot best -> the taxable gain
    used_deduction_eur: Decimal  # proceeds - optimum_gain (effective hankintameno)
    recommended_method: str  # 'todellinen_hankintameno'|'hankintameno_olettama'|'yhdistelma'
    rate_label: str  # '20%' | '40%' | '20-40%'
    tax_eur: Decimal
    effective_rate: Decimal
    covered_qty: Decimal
    shortfall_qty: Decimal
    lots: list[LotResult] = field(default_factory=list)


def compute(
    lots: list[TaxLot],
    sell_price_eur: Decimal,
    fees_eur: Decimal,
    quantity_sold: Decimal,
) -> TaxResult:
    """Compute the Finnish capital-gains tax for a single sale.

    ``lots`` are the FIFO-consumed acquisition lots that back the sale. If the
    recorded lots cover fewer shares than ``quantity_sold`` (incomplete buy
    history), the shortfall shares are still entitled to the 20%
    hankintameno-olettama (no documentation required) and the shortfall is
    reported via ``TaxResult.shortfall_qty`` so the caller can warn the user.
    """
    proceeds_total = quantity_sold * sell_price_eur
    covered_qty = sum((lot.quantity for lot in lots), ZERO)
    shortfall_qty = quantity_sold - covered_qty
    if shortfall_qty < 0:
        shortfall_qty = ZERO

    # Fees are a cost of *covered* lots; allocate pro-rata by their proceeds.
    covered_proceeds = sum((lot.quantity * sell_price_eur for lot in lots), ZERO)

    lot_results: list[LotResult] = []
    actual_cost_total = ZERO
    deemed_cost_total = ZERO
    optimum_gain = ZERO

    for lot in lots:
        proceeds_i = lot.quantity * sell_price_eur
        rate_i = deemed_rate(lot.over_10_years)
        deemed_i = proceeds_i * rate_i
        fee_i = (fees_eur * proceeds_i / covered_proceeds) if covered_proceeds else ZERO
        actual_i = lot.quantity * lot.cost_per_share_eur + fee_i

        # Pick the larger deduction => the smaller (or more negative) gain.
        if deemed_i >= actual_i:
            method = "deemed"
            deduction_i = deemed_i
        else:
            method = "actual"
            deduction_i = actual_i
        gain_i = proceeds_i - deduction_i

        actual_cost_total += lot.quantity * lot.cost_per_share_eur
        deemed_cost_total += deemed_i
        optimum_gain += gain_i

        lot_results.append(
            LotResult(
                quantity=lot.quantity,
                cost_per_share_eur=lot.cost_per_share_eur,
                over_10_years=lot.over_10_years,
                proceeds_eur=proceeds_i,
                applied_rate=rate_i,
                deemed_cost_eur=deemed_i,
                actual_cost_eur=actual_i,
                method=method,
                gain_eur=gain_i,
            )
        )

    # Shortfall shares have no acquisition records but are still entitled to
    # the 20% deemed cost (a fixed % of sale price, no proof required).
    if shortfall_qty > 0:
        proceeds_s = shortfall_qty * sell_price_eur
        deemed_s = proceeds_s * RATE_UNDER_10
        deemed_cost_total += deemed_s
        optimum_gain += proceeds_s - deemed_s

    # Aggregate single-method gains for the comparison table.
    all_actual_gain = proceeds_total - actual_cost_total - fees_eur
    all_deemed_gain = proceeds_total - deemed_cost_total

    used_deduction = proceeds_total - optimum_gain
    tax, effective_rate = capital_gains_tax(optimum_gain)

    if abs(optimum_gain - all_actual_gain) <= _EPS:
        recommended = "todellinen_hankintameno"
    elif abs(optimum_gain - all_deemed_gain) <= _EPS:
        recommended = "hankintameno_olettama"
    else:
        recommended = "yhdistelma"

    rates = {deemed_rate(lot.over_10_years) for lot in lots}
    if shortfall_qty > 0:
        rates.add(RATE_UNDER_10)
    if rates == {RATE_OVER_10}:
        rate_label = "40%"
    elif rates == {RATE_UNDER_10} or not rates:
        rate_label = "20%"
    else:
        rate_label = "20-40%"

    return TaxResult(
        proceeds_eur=proceeds_total,
        actual_cost_total_eur=actual_cost_total,
        fees_eur=fees_eur,
        deemed_cost_total_eur=deemed_cost_total,
        all_actual_gain_eur=all_actual_gain,
        all_deemed_gain_eur=all_deemed_gain,
        optimum_gain_eur=optimum_gain,
        used_deduction_eur=used_deduction,
        recommended_method=recommended,
        rate_label=rate_label,
        tax_eur=tax,
        effective_rate=effective_rate,
        covered_qty=covered_qty,
        shortfall_qty=shortfall_qty,
        lots=lot_results,
    )
