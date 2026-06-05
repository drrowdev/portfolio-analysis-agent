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


def per_sale_tax(calculation_json: dict) -> Decimal:
    """Extract the per-sale advance tax (ennakkovero) from a stored calculation.

    Falls back to 0 if the expected field is missing/unparseable so a single bad
    row never breaks the whole summary.
    """
    try:
        return Decimal(str(calculation_json["omavero"]["veron_maara"]))
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return ZERO


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
        "sales": sale_rows,
    }
