"""Tests for the ennakkovero declaration-summary service."""

from datetime import date
from decimal import Decimal

from app.services.declarations import (
    DeclarationSale,
    per_sale_tax,
    summarize_declarations,
)


def _sale(id, d, tax, declared=False, paid=None, paid_date=None):
    return DeclarationSale(
        id=id,
        sell_date=date.fromisoformat(d),
        quantity_sold="10",
        computed_tax_eur=Decimal(str(tax)),
        declared=declared,
        declared_at="2026-02-15T00:00:00" if declared else None,
        paid_amount_eur=Decimal(str(paid)) if paid is not None else None,
        paid_date=date.fromisoformat(paid_date) if paid_date else None,
    )


def test_per_sale_tax_reads_veron_maara():
    assert per_sale_tax({"omavero": {"veron_maara": 11113.38}}) == Decimal("11113.38")


def test_per_sale_tax_missing_field_is_zero():
    assert per_sale_tax({}) == Decimal("0")
    assert per_sale_tax({"omavero": {}}) == Decimal("0")


def test_empty_summary():
    s = summarize_declarations([], year=2026, symbol="MSFT")
    assert s["sale_count"] == 0
    assert s["total_tax_eur"] == "0.00"
    assert s["remaining_tax_eur"] == "0.00"
    assert s["fully_declared"] is False


def test_total_declared_remaining_split():
    sales = [
        _sale("a", "2026-01-15", "11113.38", declared=True, paid="12313.38", paid_date="2026-02-15"),
        _sale("b", "2026-06-01", "4975.28", declared=False),
        _sale("c", "2026-06-03", "2000.00", declared=False),
    ]
    s = summarize_declarations(sales, year=2026, symbol="MSFT")
    assert s["sale_count"] == 3
    assert s["declared_count"] == 1
    assert s["total_tax_eur"] == "18088.66"
    assert s["declared_tax_eur"] == "11113.38"
    assert s["remaining_tax_eur"] == "6975.28"
    # Reconciliation: paid 12313.38 vs computed 11113.38 -> overpaid 1200.00
    assert s["total_paid_eur"] == "12313.38"
    assert s["over_under_eur"] == "1200.00"
    assert s["fully_declared"] is False


def test_fully_declared_flag():
    sales = [
        _sale("a", "2026-01-15", "100.00", declared=True, paid="100.00", paid_date="2026-02-01"),
        _sale("b", "2026-02-15", "50.00", declared=True, paid="50.00", paid_date="2026-03-01"),
    ]
    s = summarize_declarations(sales, year=2026, symbol="MSFT")
    assert s["fully_declared"] is True
    assert s["remaining_tax_eur"] == "0.00"
    assert s["over_under_eur"] == "0.00"


def test_declared_without_paid_amount_counts_as_declared_not_paid():
    sales = [_sale("a", "2026-01-15", "100.00", declared=True)]
    s = summarize_declarations(sales, year=2026, symbol="MSFT")
    assert s["declared_count"] == 1
    assert s["paid_count"] == 0
    assert s["declared_tax_eur"] == "100.00"
    assert s["total_paid_eur"] == "0.00"
    # No paid amount -> no reconciliation contribution
    assert s["over_under_eur"] == "0.00"


def test_sales_sorted_by_date():
    sales = [
        _sale("late", "2026-06-01", "1.00"),
        _sale("early", "2026-01-01", "2.00"),
    ]
    s = summarize_declarations(sales, year=2026, symbol="MSFT")
    assert [row["id"] for row in s["sales"]] == ["early", "late"]
