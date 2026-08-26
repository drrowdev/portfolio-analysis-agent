"""Tests for the ennakkovero declaration-summary service."""

from datetime import date
from decimal import Decimal

from app.services.declarations import (
    DeclarationSale,
    omavero_fields,
    per_sale_tax,
    summarize_declarations,
)


def test_declaration_update_accepts_numeric_paid_amount():
    """The frontend's response coercion can turn the stored paid amount into a
    number before it round-trips; the endpoint schema must accept that."""
    import pytest

    pytest.importorskip("fastapi")
    from app.routers.tax_calculations import DeclarationUpdate

    # number in -> coerced to string
    m = DeclarationUpdate(declared=True, paid_amount_eur=12456.95)
    assert m.paid_amount_eur == "12456.95"
    # normal string still works
    m2 = DeclarationUpdate(declared=True, paid_amount_eur="6464.15")
    assert m2.paid_amount_eur == "6464.15"
    # clearing works
    m3 = DeclarationUpdate(declared=False)
    assert m3.paid_amount_eur is None


def _sale(id, d, tax, declared=False, paid=None, paid_date=None,
          proceeds="0", acquisition="0", gain="0", engine_version="2026.08",
          is_legacy=False):
    return DeclarationSale(
        id=id,
        sell_date=date.fromisoformat(d),
        quantity_sold="10",
        computed_tax_eur=Decimal(str(tax)),
        declared=declared,
        declared_at="2026-02-15T00:00:00" if declared else None,
        paid_amount_eur=Decimal(str(paid)) if paid is not None else None,
        paid_date=date.fromisoformat(paid_date) if paid_date else None,
        proceeds_eur=Decimal(str(proceeds)),
        acquisition_cost_eur=Decimal(str(acquisition)),
        gain_eur=Decimal(str(gain)),
        engine_version=engine_version,
        is_legacy=is_legacy,
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
    assert s["undeclared_tax_eur"] == "0.00"
    assert s["fully_declared"] is False


def test_no_payable_balance_is_reported():
    """The app cannot see the tax account, so it must never publish a balance.

    Netting a recorded overpayment against the year's computed tax is exactly
    what previously advised paying less than Verohallinto had invoiced.
    """
    sales = [
        _sale("a", "2026-01-15", "11113.38", declared=True, paid="12456.95", paid_date="2026-01-31"),
        _sale("b", "2026-08-05", "7031.40", declared=False),
    ]
    s = summarize_declarations(sales, year=2026, symbol="MSFT")
    for banned in (
        "remaining_to_pay_eur",
        "year_balance_eur",
        "overpaid_overall",
        "over_under_eur",
        "computed_for_paid_eur",
        "remaining_tax_eur",
    ):
        assert banned not in s, f"{banned} re-introduces an unknowable balance"


def test_total_declared_undeclared_split():
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
    assert s["undeclared_tax_eur"] == "6975.28"
    # Recorded payments are reported as-is, never netted into a balance.
    assert s["total_paid_eur"] == "12313.38"
    assert s["paid_count"] == 1
    assert s["fully_declared"] is False


def test_paid_amount_counted_even_when_not_declared():
    """Paid status is tracked per sale independently of declaration status."""
    sales = [_sale("a", "2026-01-15", "100.00", declared=False, paid="100.00", paid_date="2026-02-01")]
    s = summarize_declarations(sales, year=2026, symbol="MSFT")
    assert s["declared_count"] == 0
    assert s["paid_count"] == 1
    assert s["total_paid_eur"] == "100.00"


def test_legacy_rows_are_counted_and_flagged():
    sales = [
        _sale("old", "2026-01-15", "100.00", engine_version=None, is_legacy=True),
        _sale("new", "2026-02-15", "50.00"),
    ]
    s = summarize_declarations(sales, year=2026, symbol="MSFT")
    assert s["legacy_count"] == 1
    old_row = next(r for r in s["sales"] if r["id"] == "old")
    assert old_row["is_legacy"] is True
    assert old_row["engine_version"] is None
    new_row = next(r for r in s["sales"] if r["id"] == "new")
    assert new_row["is_legacy"] is False
    assert new_row["engine_version"] == "2026.08"


def test_fully_declared_flag():
    sales = [
        _sale("a", "2026-01-15", "100.00", declared=True, paid="100.00", paid_date="2026-02-01"),
        _sale("b", "2026-02-15", "50.00", declared=True, paid="50.00", paid_date="2026-03-01"),
    ]
    s = summarize_declarations(sales, year=2026, symbol="MSFT")
    assert s["fully_declared"] is True
    assert s["undeclared_tax_eur"] == "0.00"


def test_declared_without_paid_amount_counts_as_declared_not_paid():
    sales = [_sale("a", "2026-01-15", "100.00", declared=True)]
    s = summarize_declarations(sales, year=2026, symbol="MSFT")
    assert s["declared_count"] == 1
    assert s["paid_count"] == 0
    assert s["declared_tax_eur"] == "100.00"
    assert s["total_paid_eur"] == "0.00"


def test_sales_sorted_by_date():
    sales = [
        _sale("late", "2026-06-01", "1.00"),
        _sale("early", "2026-01-01", "2.00"),
    ]
    s = summarize_declarations(sales, year=2026, symbol="MSFT")
    assert [row["id"] for row in s["sales"]] == ["early", "late"]


def test_omavero_fields_extraction():
    cj = {
        "omavero": {
            "luovutushinta": 19762.46,
            "hankintameno_kaytetty": 5129.29,
            "luovutusvoitto": 14633.17,
        }
    }
    f = omavero_fields(cj)
    assert f["proceeds"] == Decimal("19762.46")
    assert f["acquisition"] == Decimal("5129.29")
    assert f["gain"] == Decimal("14633.17")


def test_omavero_fields_fallback_acquisition():
    # No explicit hankintameno_kaytetty -> derive as proceeds - gain.
    cj = {"omavero": {"luovutushinta": 100, "luovutusvoitto": 40}}
    f = omavero_fields(cj)
    assert f["acquisition"] == Decimal("60")


def test_form_field_totals_and_loss_split():
    sales = [
        _sale("a", "2026-01-15", "1000.00", proceeds="20000", acquisition="5000", gain="15000"),
        _sale("b", "2026-06-01", "0.00", proceeds="3000", acquisition="4000", gain="-1000"),
    ]
    s = summarize_declarations(sales, year=2026, symbol="MSFT")
    assert s["total_proceeds_eur"] == "23000.00"
    assert s["total_acquisition_cost_eur"] == "9000.00"
    assert s["total_gain_eur"] == "15000.00"
    assert s["total_loss_eur"] == "1000.00"
    # Per-sale: the loss row exposes loss, zero gain.
    loss_row = next(r for r in s["sales"] if r["id"] == "b")
    assert loss_row["gain_eur"] == "0.00"
    assert loss_row["loss_eur"] == "1000.00"
    gain_row = next(r for r in s["sales"] if r["id"] == "a")
    assert gain_row["gain_eur"] == "15000.00"
    assert gain_row["loss_eur"] == "0.00"

