"""Pure (DB-free) summarisation of ennakkovero declaration status.

A saved ``TaxCalculation`` carries the per-sale advance tax (``omavero.veron_maara``
inside its stored JSON) and, once the user has filed/paid it in OmaVero, a
``declared_at`` timestamp plus the actual ``paid_amount_eur`` / ``paid_date``.

Finnish capital-gains tax is assessed once per year on the cumulative total, and
the per-sale figures are *marginal* (they stack chronologically), so they sum
exactly to the year's total advance tax. This module turns a list of saved
calculations into a Total / Declared / Remaining view plus a paid-vs-computed
reconciliation for the sales the user has actually paid.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

ZERO = Decimal("0")


@dataclass
class DeclarationSale:
    """One saved per-sale calculation with its declaration state."""

    id: str
    sell_date: date
    quantity_sold: str
    computed_tax_eur: Decimal
    declared: bool
    declared_at: Optional[str] = None
    paid_amount_eur: Optional[Decimal] = None
    paid_date: Optional[date] = None
    # OmaVero form fields for this sale (for filling the annual return).
    proceeds_eur: Decimal = ZERO  # Luovutushinta / myyntihinta
    acquisition_cost_eur: Decimal = ZERO  # Hankintameno (käytetty vähennys)
    gain_eur: Decimal = ZERO  # Luovutusvoitto (>0) tai -tappio (<0)


def per_sale_tax(calculation_json: dict) -> Decimal:
    """Extract the per-sale advance tax (ennakkovero) from a stored calculation.

    Falls back to 0 if the expected field is missing/unparseable so a single bad
    row never breaks the whole summary.
    """
    try:
        return Decimal(str(calculation_json["omavero"]["veron_maara"]))
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return ZERO


def _omavero_decimal(calculation_json: dict, key: str) -> Decimal:
    """Read a numeric OmaVero field from a stored calculation (0 on failure)."""
    try:
        return Decimal(str(calculation_json["omavero"][key]))
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return ZERO


def omavero_fields(calculation_json: dict) -> dict:
    """Extract the OmaVero form fields (proceeds, acquisition cost, gain) for a sale."""
    proceeds = _omavero_decimal(calculation_json, "luovutushinta")
    gain = _omavero_decimal(calculation_json, "luovutusvoitto")
    # Prefer the explicit "used deduction"; fall back to proceeds − gain so the
    # three numbers always reconcile even for older saved calculations.
    used = calculation_json.get("omavero", {}).get("hankintameno_kaytetty")
    if used is not None:
        try:
            acquisition = Decimal(str(used))
        except (TypeError, ValueError, ArithmeticError):
            acquisition = proceeds - gain
    else:
        acquisition = proceeds - gain
    return {"proceeds": proceeds, "acquisition": acquisition, "gain": gain}


def _money(value) -> str:
    """Render a Decimal as a 2-dp string for JSON transport (avoids float drift)."""
    return str(Decimal(value).quantize(Decimal("0.01")))


def summarize_declarations(sales: list[DeclarationSale], *, year: int, symbol: str) -> dict:
    """Aggregate per-sale declaration status into year totals + reconciliation.

    Returns a JSON-serialisable dict with string money values (2 dp).
    """
    total_tax = ZERO
    declared_tax = ZERO
    remaining_tax = ZERO
    total_paid = ZERO
    computed_for_paid = ZERO  # computed tax of declared sales that have a paid amount
    declared_count = 0
    paid_count = 0

    # OmaVero form-field totals for the year.
    total_proceeds = ZERO  # Luovutushinnat
    total_acquisition = ZERO  # Hankintamenot
    total_gain = ZERO  # Luovutusvoitot (positive sales only)
    total_loss = ZERO  # Luovutustappiot (magnitude of negative sales)

    ordered = sorted(sales, key=lambda s: (s.sell_date, s.id))
    sale_rows = []
    for s in ordered:
        total_tax += s.computed_tax_eur
        if s.declared:
            declared_count += 1
            declared_tax += s.computed_tax_eur
            if s.paid_amount_eur is not None:
                paid_count += 1
                total_paid += s.paid_amount_eur
                computed_for_paid += s.computed_tax_eur
        else:
            remaining_tax += s.computed_tax_eur

        total_proceeds += s.proceeds_eur
        total_acquisition += s.acquisition_cost_eur
        if s.gain_eur >= 0:
            total_gain += s.gain_eur
        else:
            total_loss += -s.gain_eur

        sale_rows.append(
            {
                "id": s.id,
                "sell_date": s.sell_date.isoformat(),
                "quantity_sold": s.quantity_sold,
                "computed_tax_eur": _money(s.computed_tax_eur),
                "declared": s.declared,
                "declared_at": s.declared_at,
                "paid_amount_eur": _money(s.paid_amount_eur) if s.paid_amount_eur is not None else None,
                "paid_date": s.paid_date.isoformat() if s.paid_date else None,
                # OmaVero form fields
                "proceeds_eur": _money(s.proceeds_eur),
                "acquisition_cost_eur": _money(s.acquisition_cost_eur),
                "gain_eur": _money(s.gain_eur) if s.gain_eur >= 0 else "0.00",
                "loss_eur": _money(-s.gain_eur) if s.gain_eur < 0 else "0.00",
            }
        )

    over_under = total_paid - computed_for_paid  # >0 overpaid, <0 underpaid

    return {
        "year": year,
        "symbol": symbol,
        "sale_count": len(ordered),
        "declared_count": declared_count,
        "paid_count": paid_count,
        "total_tax_eur": _money(total_tax),
        "declared_tax_eur": _money(declared_tax),
        "remaining_tax_eur": _money(remaining_tax),
        "total_paid_eur": _money(total_paid),
        "computed_for_paid_eur": _money(computed_for_paid),
        "over_under_eur": _money(over_under),
        "fully_declared": len(ordered) > 0 and declared_count == len(ordered),
        # OmaVero form-field totals for the year
        "total_proceeds_eur": _money(total_proceeds),
        "total_acquisition_cost_eur": _money(total_acquisition),
        "total_gain_eur": _money(total_gain),
        "total_loss_eur": _money(total_loss),
        "sales": sale_rows,
    }
