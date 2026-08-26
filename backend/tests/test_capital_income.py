"""Tests for the year-level capital-income tracker (gains + dividends)."""

from datetime import date
from decimal import Decimal

from app.services import tax as tax_math
from app.services.capital_income import (
    LISTED_DIVIDEND_TAXABLE_FRACTION,
    IncomeTxn,
    compute_capital_income,
)

YEAR = 2026


def _buy(account, sym, d, qty, price, treatment="standard"):
    return IncomeTxn(
        account_id=account,
        tax_treatment=treatment,
        symbol=sym,
        txn_type="buy",
        date=d,
        quantity=Decimal(str(qty)),
        price_eur=Decimal(str(price)),
        total_eur=Decimal(str(qty)) * Decimal(str(price)),
        fees=Decimal("0"),
    )


def _sell(account, sym, d, qty, price, treatment="standard"):
    return IncomeTxn(
        account_id=account,
        tax_treatment=treatment,
        symbol=sym,
        txn_type="sell",
        date=d,
        quantity=Decimal(str(qty)),
        price_eur=Decimal(str(price)),
        total_eur=Decimal(str(qty)) * Decimal(str(price)),
        fees=Decimal("0"),
    )


def _div(account, sym, d, gross, treatment="standard"):
    return IncomeTxn(
        account_id=account,
        tax_treatment=treatment,
        symbol=sym,
        txn_type="dividend",
        date=d,
        quantity=Decimal("0"),
        price_eur=Decimal("0"),
        total_eur=Decimal(str(gross)),
        fees=Decimal("0"),
    )


def test_simple_gain_and_dividend():
    txns = [
        _buy("acc1", "MSFT", date(2024, 1, 10), 10, 100),
        _sell("acc1", "MSFT", date(YEAR, 3, 1), 10, 150),
        _div("acc1", "MSFT", date(YEAR, 6, 1), 200),
    ]
    s = compute_capital_income(txns, YEAR)

    # Gain: proceeds 1500 - cost 1000 = 500 (actual beats 20% deemed of 300).
    assert s.taxable_gains_eur == Decimal("500")
    assert s.gross_dividends_eur == Decimal("200")
    assert s.taxable_dividends_eur == Decimal("200") * LISTED_DIVIDEND_TAXABLE_FRACTION
    assert s.combined_taxable_eur == Decimal("500") + Decimal("170")
    assert s.sale_count == 1
    assert s.dividend_payment_count == 1


def test_dividends_can_be_excluded_from_the_bracket_base():
    """Ennakkovero is applied for on gains only, so the bracket must match.

    Dividends are reported on the annual return rather than through the
    advance-tax application, so Verohallinto's ennakkovero basis contains no
    dividend income. Including them here would push a sale into 34 % earlier
    than the tax decision does. They are still reported separately.
    """
    txns = [
        _buy("acc1", "MSFT", date(2024, 1, 10), 10, 100),
        _sell("acc1", "MSFT", date(YEAR, 3, 1), 10, 150),
        _div("acc1", "MSFT", date(YEAR, 6, 1), 200),
    ]

    with_div = compute_capital_income(txns, YEAR)
    without_div = compute_capital_income(txns, YEAR, include_dividends=False)

    # Gains are identical either way.
    assert with_div.taxable_gains_eur == without_div.taxable_gains_eur == Decimal("500")
    # Only the bracket base changes.
    assert with_div.combined_taxable_eur == Decimal("670")
    assert without_div.combined_taxable_eur == Decimal("500")
    # Dividends are still visible, just not in the base.
    assert without_div.gross_dividends_eur == Decimal("200")
    assert without_div.taxable_dividends_eur == Decimal("170")
    assert without_div.dividend_payment_count == 1


def test_excluding_dividends_lowers_the_estimated_tax_to_gains_only():
    txns = [
        _buy("acc1", "MSFT", date(2024, 1, 10), 1000, 10),
        _sell("acc1", "MSFT", date(YEAR, 3, 1), 1000, 50),
        _div("acc1", "MSFT", date(YEAR, 6, 1), 10000),
    ]
    gains_only = compute_capital_income(txns, YEAR, include_dividends=False)

    # Gain 40,000 -> 30k at 30 % + 10k at 34 %.
    assert gains_only.combined_taxable_eur == Decimal("40000")
    assert gains_only.estimated_tax_eur == Decimal("9000") + Decimal("3400")


def test_buy_commission_increases_fifo_acquisition_basis():
    buy = _buy("acc1", "MSFT", date(2024, 1, 10), 1, 100)
    buy.fees = Decimal("10")
    txns = [
        buy,
        _sell("acc1", "MSFT", date(YEAR, 3, 1), 1, 110),
    ]

    summary = compute_capital_income(txns, YEAR)

    assert summary.taxable_gains_eur == Decimal("0")


def test_ost_gains_and_dividends_excluded():
    txns = [
        _buy("ost", "NOKIA", date(2024, 1, 1), 100, 4, treatment="deferred"),
        _sell("ost", "NOKIA", date(YEAR, 5, 1), 100, 6, treatment="deferred"),
        _div("ost", "NOKIA", date(YEAR, 4, 1), 50, treatment="deferred"),
    ]
    s = compute_capital_income(txns, YEAR)

    assert s.taxable_gains_eur == Decimal("0")
    assert s.gross_dividends_eur == Decimal("0")
    assert s.combined_taxable_eur == Decimal("0")
    assert s.excluded_ost_sale_count == 1
    assert s.excluded_ost_dividends_eur == Decimal("50")


def test_accumulating_etf_has_no_dividends():
    # SXR8-style: only buys/sells, never a dividend row -> nothing extra to add.
    txns = [
        _buy("acc1", "SXR8", date(2024, 1, 1), 5, 80),
        _sell("acc1", "SXR8", date(YEAR, 2, 1), 5, 100),
    ]
    s = compute_capital_income(txns, YEAR)
    assert s.gross_dividends_eur == Decimal("0")
    assert s.taxable_dividends_eur == Decimal("0")
    assert s.taxable_gains_eur == Decimal("100")  # 500 - 400


def test_dividend_85_percent_fraction():
    txns = [_div("acc1", "MSFT", date(YEAR, 6, 1), 1000)]
    s = compute_capital_income(txns, YEAR)
    assert s.gross_dividends_eur == Decimal("1000")
    assert s.taxable_dividends_eur == Decimal("850")


def test_deemed_acquisition_cost_beats_actual_for_old_lot():
    # >10y hold -> 40% deemed. Tiny actual cost so deemed (40%) wins.
    txns = [
        _buy("acc1", "OLD", date(2010, 1, 1), 10, 1),
        _sell("acc1", "OLD", date(YEAR, 1, 2), 10, 100),
    ]
    s = compute_capital_income(txns, YEAR)
    # proceeds 1000; deemed cost 40% = 400 -> gain 600 (beats actual gain 990).
    assert s.taxable_gains_eur == Decimal("600")


def test_per_account_fifo_isolation():
    # Same symbol in two accounts; lots must not cross accounts.
    txns = [
        _buy("acc1", "MSFT", date(2024, 1, 1), 10, 100),
        _buy("acc2", "MSFT", date(2024, 1, 1), 10, 50),
        _sell("acc1", "MSFT", date(YEAR, 1, 2), 10, 120),  # gain 200
    ]
    s = compute_capital_income(txns, YEAR)
    # If FIFO leaked, the cheaper acc2 lot would inflate the gain.
    assert s.taxable_gains_eur == Decimal("200")
    assert s.sale_count == 1


def test_losses_net_against_dividends():
    txns = [
        _buy("acc1", "LOSS", date(2024, 1, 1), 10, 100),
        _sell("acc1", "LOSS", date(YEAR, 1, 2), 10, 60),  # loss -400
        _div("acc1", "MSFT", date(YEAR, 6, 1), 200),       # taxable 170
    ]
    s = compute_capital_income(txns, YEAR)
    assert s.taxable_gains_eur == Decimal("-400")
    assert s.taxable_dividends_eur == Decimal("170")
    assert s.combined_taxable_eur == Decimal("-230")
    assert s.estimated_tax_eur == Decimal("0")  # net negative -> no tax


def test_30_34_bracket_split():
    # Combined taxable income above 30k -> 34% on the excess.
    txns = [
        _buy("acc1", "BIG", date(2024, 1, 1), 1, 1),
        _sell("acc1", "BIG", date(YEAR, 1, 2), 1, 40001),  # gain ~40000
    ]
    s = compute_capital_income(txns, YEAR)
    expected_tax, _ = tax_math.capital_gains_tax(s.combined_taxable_eur)
    assert s.estimated_tax_eur == expected_tax
    assert s.amount_over_threshold_eur == s.combined_taxable_eur - Decimal("30000")


def test_negative_dividend_rows_are_withholding_not_income():
    # Nordnet stores OSINKO (+gross) and ENNAKKOPIDÄTYS (-withholding) both as
    # "dividend". Only the positive gross row is taxable income.
    txns = [
        _div("acc1", "REG1V", date(YEAR, 4, 5), 486.40),   # OSINKO gross
        _div("acc1", "REG1V", date(YEAR, 4, 5), -124.03),  # ENNAKKOPIDÄTYS
    ]
    s = compute_capital_income(txns, YEAR)
    assert s.gross_dividends_eur == Decimal("486.40")
    assert s.taxable_dividends_eur == Decimal("486.40") * LISTED_DIVIDEND_TAXABLE_FRACTION
    assert s.dividend_payment_count == 1


def test_prior_year_sales_excluded_but_feed_fifo():
    # A sale in a prior year must consume FIFO lots but not count this year.
    txns = [
        _buy("acc1", "MSFT", date(2023, 1, 1), 10, 100),
        _sell("acc1", "MSFT", date(2025, 1, 1), 5, 200),   # prior year
        _sell("acc1", "MSFT", date(YEAR, 1, 1), 5, 200),   # this year
    ]
    s = compute_capital_income(txns, YEAR)
    # Only the in-year sale counts: 5 * (200-100) = 500.
    assert s.taxable_gains_eur == Decimal("500")
    assert s.sale_count == 1


def test_before_date_counts_only_earlier_income():
    # before_date positions a sale: only income realised strictly before it
    # counts, while later sells still consume FIFO lots correctly.
    txns = [
        _buy("acc1", "MSFT", date(2024, 1, 1), 30, 100),
        _sell("acc1", "MSFT", date(YEAR, 1, 15), 10, 150),  # gain 500
        _div("acc1", "MSFT", date(YEAR, 3, 1), 200),        # taxable 170
        _sell("acc1", "MSFT", date(YEAR, 6, 1), 10, 200),   # gain 1000 (later)
    ]
    # Income strictly before the June sale: Jan gain 500 + March dividend 170.
    prior = compute_capital_income(txns, YEAR, before_date=date(YEAR, 6, 1))
    assert prior.combined_taxable_eur == Decimal("670")
    assert prior.sale_count == 1

    # Income strictly before the FIRST (Jan) sale: nothing yet.
    first = compute_capital_income(txns, YEAR, before_date=date(YEAR, 1, 15))
    assert first.combined_taxable_eur == Decimal("0")
    assert first.sale_count == 0

    # The later sale's gain is unaffected by the cutoff (FIFO still consumed):
    # full year = 500 + 170 + 1000 = 1670.
    full = compute_capital_income(txns, YEAR)
    assert full.combined_taxable_eur == Decimal("1670")


def test_before_date_excludes_same_day_sales():
    # Sales on exactly before_date are NOT counted as prior (strictly-before).
    txns = [
        _buy("acc1", "MSFT", date(2024, 1, 1), 20, 100),
        _sell("acc1", "MSFT", date(YEAR, 4, 1), 10, 150),  # same day as cutoff
    ]
    s = compute_capital_income(txns, YEAR, before_date=date(YEAR, 4, 1))
    assert s.combined_taxable_eur == Decimal("0")
    assert s.sale_count == 0
