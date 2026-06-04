"""Regression tests for the Finnish capital-gains tax math (app.services.tax).

These lock in the per-lot hankintameno-olettama fix. The headline numbers
(Scenario A: taxable €23,788.00 / tax €7,136.40) were independently verified
against the Finnish vero.fi rules before being encoded here.
"""

from decimal import Decimal

import pytest

from app.services import tax


def D(x: str) -> Decimal:
    return Decimal(x)


# ---------------------------------------------------------------------------
# capital_gains_tax: 30% up to 30k, 34% above
# ---------------------------------------------------------------------------

def test_capital_gains_tax_zero_and_negative():
    assert tax.capital_gains_tax(D("0")) == (D("0"), D("0"))
    assert tax.capital_gains_tax(D("-500")) == (D("0"), D("0"))


def test_capital_gains_tax_low_bracket():
    t, rate = tax.capital_gains_tax(D("10000"))
    assert t == D("3000")
    assert rate == D("0.30")


def test_capital_gains_tax_boundary_30k():
    t, rate = tax.capital_gains_tax(D("30000"))
    assert t == D("9000")
    assert rate == D("0.30")


def test_capital_gains_tax_high_bracket():
    # 30000*0.30 + 10000*0.34 = 9000 + 3400 = 12400
    t, rate = tax.capital_gains_tax(D("40000"))
    assert t == D("12400")
    assert rate == D("12400") / D("40000")


# ---------------------------------------------------------------------------
# bracket_total_tax: total year tax on net positive capital income
# ---------------------------------------------------------------------------

def test_bracket_total_tax():
    assert tax.bracket_total_tax(D("0")) == D("0")
    assert tax.bracket_total_tax(D("-1000")) == D("0")
    assert tax.bracket_total_tax(D("20000")) == D("6000")
    assert tax.bracket_total_tax(D("30000")) == D("9000")
    # 9000 + 5000*0.34 = 10700
    assert tax.bracket_total_tax(D("35000")) == D("10700")


# ---------------------------------------------------------------------------
# capital_gains_tax with prior_year_income: marginal stacking on the bracket
# ---------------------------------------------------------------------------

def test_marginal_prior_zero_backward_compatible():
    # prior=0 reduces to the plain per-sale bracket.
    assert tax.capital_gains_tax(D("10000"), D("0")) == tax.capital_gains_tax(D("10000"))


def test_marginal_prior_below_threshold_crossing():
    # prior 25k, gain 10k: 5k at 30% (to reach 30k) + 5k at 34% = 1500 + 1700.
    t, rate = tax.capital_gains_tax(D("10000"), D("25000"))
    assert t == D("3200")
    assert rate == D("3200") / D("10000")


def test_marginal_prior_already_over_threshold():
    # prior 35k already above 30k -> the whole gain is taxed at 34%.
    t, rate = tax.capital_gains_tax(D("5000"), D("35000"))
    assert t == D("1700")
    assert rate == D("0.34")


def test_marginal_prior_at_threshold():
    # prior exactly 30k -> entire gain at 34%.
    t, rate = tax.capital_gains_tax(D("5000"), D("30000"))
    assert t == D("1700")
    assert rate == D("0.34")


def test_marginal_negative_prior_shields_gain():
    # A net YTD loss of 5k shields the first 5k of gain; remainder at 30%.
    # prior=-5000, gain=10000 -> taxable 5000 at 30% = 1500.
    t, rate = tax.capital_gains_tax(D("10000"), D("-5000"))
    assert t == D("1500")
    assert rate == D("1500") / D("10000")


def test_marginal_negative_prior_fully_shields():
    # Loss larger than the gain -> no tax.
    t, rate = tax.capital_gains_tax(D("3000"), D("-5000"))
    assert t == D("0")
    assert rate == D("0")


def test_marginal_loss_shield_plus_threshold_crossing():
    # prior=-2000, gain=40000: taxable income 0..38000.
    # 30000 at 30% (9000) + 8000 at 34% (2720) = 11720.
    t, _ = tax.capital_gains_tax(D("40000"), D("-2000"))
    assert t == D("11720")


# ---------------------------------------------------------------------------
# deemed_rate per lot
# ---------------------------------------------------------------------------

def test_deemed_rate_per_holding():
    assert tax.deemed_rate(False) == D("0.20")
    assert tax.deemed_rate(True) == D("0.40")


# ---------------------------------------------------------------------------
# Scenario B (control): all lots > 10 years -> pure 40% olettama
#   50 @ €25 (13y) + 50 @ €35 (11y), sell 100 @ €30, no fees
#   proceeds 3000; deemed 40% = 1200; gain 1800... scaled up below.
# Use the harness figures: 100 shares @ €300 sale price.
# ---------------------------------------------------------------------------

def test_scenario_b_all_over_10_uses_40_percent():
    lots = [
        tax.TaxLot(D("50"), D("25"), over_10_years=True),
        tax.TaxLot(D("50"), D("35"), over_10_years=True),
    ]
    r = tax.compute(lots, sell_price_eur=D("400"), fees_eur=D("0"), quantity_sold=D("100"))
    # proceeds = 100 * 400 = 40000; deemed 40% = 16000; gain = 24000
    assert r.proceeds_eur == D("40000")
    assert r.deemed_cost_total_eur == D("16000")
    assert r.optimum_gain_eur == D("24000")
    assert r.tax_eur == D("7200")  # 9000 + (24000-30000<0)->no; 24000<=30000 => 24000*0.30
    assert r.recommended_method == "hankintameno_olettama"
    assert r.rate_label == "40%"


# ---------------------------------------------------------------------------
# Per-lot rate: an old lot keeps 40% even when a recent lot is present.
# ---------------------------------------------------------------------------

def test_old_lot_keeps_40_percent_despite_recent_lot():
    lots = [
        tax.TaxLot(D("50"), D("10"), over_10_years=True),   # cheap, very old
        tax.TaxLot(D("50"), D("390"), over_10_years=False),  # expensive, recent
    ]
    r = tax.compute(lots, sell_price_eur=D("400"), fees_eur=D("0"), quantity_sold=D("100"))
    # Old lot: proceeds 20000, deemed 40%=8000 vs actual 500 -> deemed (gain 12000)
    # New lot: proceeds 20000, deemed 20%=4000 vs actual 19500 -> actual (gain 500)
    assert r.lots[0].applied_rate == D("0.40")
    assert r.lots[0].method == "deemed"
    assert r.lots[1].applied_rate == D("0.20")
    assert r.lots[1].method == "actual"
    assert r.optimum_gain_eur == D("12500")
    assert r.recommended_method == "yhdistelma"
    assert r.rate_label == "20-40%"


# ---------------------------------------------------------------------------
# Loss lot uses actual cost (deemed would understate the deduction).
# ---------------------------------------------------------------------------

def test_loss_lot_uses_actual_cost():
    lots = [tax.TaxLot(D("100"), D("500"), over_10_years=False)]
    r = tax.compute(lots, sell_price_eur=D("400"), fees_eur=D("0"), quantity_sold=D("100"))
    # actual cost 50000 vs deemed 20% = 8000 -> actual wins, gain = -10000
    assert r.lots[0].method == "actual"
    assert r.optimum_gain_eur == D("-10000")
    assert r.tax_eur == D("0")
    assert r.recommended_method == "todellinen_hankintameno"


# ---------------------------------------------------------------------------
# Shortfall coverage guard: fewer recorded lots than sold quantity.
# ---------------------------------------------------------------------------

def test_shortfall_shares_get_20_percent_deemed():
    lots = [tax.TaxLot(D("40"), D("100"), over_10_years=False)]
    r = tax.compute(lots, sell_price_eur=D("400"), fees_eur=D("0"), quantity_sold=D("100"))
    assert r.covered_qty == D("40")
    assert r.shortfall_qty == D("60")
    # covered lot: proceeds 16000, deemed 3200 vs actual 4000 -> actual, gain 12000
    # shortfall: proceeds 24000, deemed 20%=4800, gain 19200
    assert r.optimum_gain_eur == D("31200")


# ---------------------------------------------------------------------------
# Fee allocation pro-rata across covered lots.
# ---------------------------------------------------------------------------

def test_fees_allocated_pro_rata():
    lots = [
        tax.TaxLot(D("50"), D("390"), over_10_years=False),
        tax.TaxLot(D("50"), D("390"), over_10_years=False),
    ]
    r = tax.compute(lots, sell_price_eur=D("400"), fees_eur=D("100"), quantity_sold=D("100"))
    # Each lot: proceeds 20000, actual 50*390 + 50 fee = 19550 vs deemed 4000 -> actual
    # gain per lot = 20000 - 19550 = 450; total 900
    assert r.optimum_gain_eur == D("900")
    assert r.lots[0].actual_cost_eur == D("19550")


# ---------------------------------------------------------------------------
# Scenario A (headline regression): the mixed-lot case that previously
# overpaid because a single recent lot forced the whole sale to 20%.
#   Sell 100 sh @ €400, fees €30. Lots (qty, €/sh, holding):
#     30 @ €25  (13y, >=10y) -> deemed 40%  gain 7200
#     30 @ €35  (12y, >=10y) -> deemed 40%  gain 7200
#     20 @ €90  (8y,  <10y)  -> actual      gain 6194
#     20 @ €240 (4y,  <10y)  -> actual      gain 3194
#   Per-lot optimum taxable = €23,788.00, tax = €7,136.40.
#   (As-coded forced all lots to 20% -> overpaid ~€2,397.)
# ---------------------------------------------------------------------------

def test_scenario_a_mixed_lots_per_lot_optimum():
    lots = [
        tax.TaxLot(D("30"), D("25"), over_10_years=True),
        tax.TaxLot(D("30"), D("35"), over_10_years=True),
        tax.TaxLot(D("20"), D("90"), over_10_years=False),
        tax.TaxLot(D("20"), D("240"), over_10_years=False),
    ]
    r = tax.compute(lots, sell_price_eur=D("400"), fees_eur=D("30"), quantity_sold=D("100"))
    assert r.optimum_gain_eur == D("23788.00")
    assert r.tax_eur == D("7136.40")
    assert r.recommended_method == "yhdistelma"
    assert r.rate_label == "20-40%"
    # Per-lot gains lock in the fee pro-rata + method choice.
    assert [l.gain_eur for l in r.lots] == [D("7200"), D("7200"), D("6194"), D("3194")]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
