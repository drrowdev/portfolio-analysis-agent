"""Year-level Finnish capital-income aggregation for the €30,000 bracket tracker.

Pure, database-free so it can be unit-tested in isolation. The router fetches
transactions + account tax treatments from the DB and hands plain ``IncomeTxn``
rows to :func:`compute_capital_income`.

What counts as taxable capital income for the €30,000 / 34 % bracket:

- **Realized capital gains** from every account EXCEPT an OST
  (``tax_treatment == "deferred"``), whose gains are taxed only on withdrawal.
  Gains use the same per-lot best-of hankintameno-olettama engine as the
  ennakkovero calculation (:mod:`app.services.tax`).
- **Dividends** from every account EXCEPT an OST. Listed-share dividends are
  **85 % taxable** capital income (15 % tax-free, TVL 33a §); accumulating ETFs
  pay nothing out so they simply have no dividend rows.

Capital losses are netted against the combined capital income (deductible from
all capital income since 2016). The 30 %/34 % bracket is then applied to the
combined net figure — the €30,000 threshold is a per-year total, not per sale.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.services import tax as tax_math

DEFERRED = "deferred"  # OST tax treatment: taxed only on withdrawal
LISTED_DIVIDEND_TAXABLE_FRACTION = Decimal("0.85")  # TVL 33a §: 15% tax-free

BUY_TYPES = {"buy", "espp_purchase"}
SELL_TYPES = {"sell", "espp_sale"}
DIVIDEND_TYPE = "dividend"


@dataclass
class IncomeTxn:
    """A flattened transaction row with its account's tax treatment."""

    account_id: str
    tax_treatment: str
    symbol: str
    txn_type: str
    date: date
    quantity: Decimal
    price_eur: Decimal
    total_eur: Decimal
    fees: Decimal = Decimal("0")


@dataclass
class SaleGain:
    account_id: str
    symbol: str
    sell_date: date
    quantity: Decimal
    proceeds_eur: Decimal
    gain_eur: Decimal


@dataclass
class DividendItem:
    symbol: str
    gross_eur: Decimal
    taxable_eur: Decimal
    payments: int


@dataclass
class CapitalIncomeSummary:
    year: int
    taxable_gains_eur: Decimal           # net optimum gains (can be negative)
    gross_dividends_eur: Decimal
    taxable_dividends_eur: Decimal       # 85% of gross
    combined_taxable_eur: Decimal        # gains + taxable dividends (floored at >= losses)
    bracket_threshold_eur: Decimal
    remaining_at_low_rate_eur: Decimal
    amount_over_threshold_eur: Decimal
    estimated_tax_eur: Decimal
    effective_rate: Decimal
    low_rate: Decimal
    high_rate: Decimal
    sale_count: int
    dividend_payment_count: int
    sales: list[SaleGain] = field(default_factory=list)
    dividends: list[DividendItem] = field(default_factory=list)
    excluded_ost_dividends_eur: Decimal = Decimal("0")
    excluded_ost_sale_count: int = 0


def _taxable_gains_for_year(txns: list[IncomeTxn], year: int) -> tuple[list[SaleGain], int]:
    """Per (account, symbol) FIFO best-of-olettama gains for sells in ``year``.

    OST (deferred) accounts are skipped entirely. Cost basis is per securities
    account, so lots from one account never satisfy sells in another.
    Returns (in-year taxable sales, count of skipped OST in-year sales).
    """
    groups: dict[tuple[str, str], list[IncomeTxn]] = {}
    for t in txns:
        if t.txn_type in BUY_TYPES or t.txn_type in SELL_TYPES:
            groups.setdefault((t.account_id, t.symbol), []).append(t)

    sales: list[SaleGain] = []
    excluded_ost = 0

    for (account_id, symbol), rows in groups.items():
        rows.sort(key=lambda r: r.date)
        deferred = rows[0].tax_treatment == DEFERRED

        # FIFO lot queue: [qty_remaining, price_eur, purchase_date]
        lots: list[list] = []
        for r in rows:
            if r.txn_type in BUY_TYPES:
                if r.quantity and r.quantity > 0:
                    lots.append([r.quantity, r.price_eur, r.date])
                continue

            # A sell: consume lots FIFO and (if in-year, non-OST) score the gain.
            remaining = r.quantity or Decimal("0")
            consumed: list[tax_math.TaxLot] = []
            while remaining > 0 and lots:
                lot_qty, lot_price, lot_date = lots[0]
                take = lot_qty if lot_qty <= remaining else remaining
                over_10 = tax_math.held_at_least_10_years(lot_date, r.date)
                consumed.append(
                    tax_math.TaxLot(
                        quantity=take, cost_per_share_eur=lot_price, over_10_years=over_10
                    )
                )
                if lot_qty <= remaining:
                    remaining -= lot_qty
                    lots.pop(0)
                else:
                    lots[0][0] = lot_qty - remaining
                    remaining = Decimal("0")

            if r.date.year != year:
                continue
            if deferred:
                excluded_ost += 1
                continue

            result = tax_math.compute(
                consumed, r.price_eur, r.fees or Decimal("0"), r.quantity or Decimal("0")
            )
            sales.append(
                SaleGain(
                    account_id=account_id,
                    symbol=symbol,
                    sell_date=r.date,
                    quantity=r.quantity or Decimal("0"),
                    proceeds_eur=result.proceeds_eur,
                    gain_eur=result.optimum_gain_eur,
                )
            )

    sales.sort(key=lambda s: s.sell_date)
    return sales, excluded_ost


def _dividends_for_year(
    txns: list[IncomeTxn], year: int
) -> tuple[list[DividendItem], Decimal, int]:
    """Aggregate taxable dividends (85% of gross) from non-OST accounts.

    Returns (per-symbol items, excluded OST gross dividends, OST payment count).
    """
    by_symbol: dict[str, DividendItem] = {}
    excluded_ost_gross = Decimal("0")

    for t in txns:
        if t.txn_type != DIVIDEND_TYPE or t.date.year != year:
            continue
        gross = t.total_eur or Decimal("0")
        if t.tax_treatment == DEFERRED:
            excluded_ost_gross += gross
            continue
        item = by_symbol.get(t.symbol)
        if item is None:
            item = DividendItem(symbol=t.symbol, gross_eur=Decimal("0"),
                                taxable_eur=Decimal("0"), payments=0)
            by_symbol[t.symbol] = item
        item.gross_eur += gross
        item.taxable_eur += gross * LISTED_DIVIDEND_TAXABLE_FRACTION
        item.payments += 1

    items = sorted(by_symbol.values(), key=lambda d: d.gross_eur, reverse=True)
    return items, excluded_ost_gross, 0


def compute_capital_income(txns: list[IncomeTxn], year: int) -> CapitalIncomeSummary:
    """Aggregate a year's taxable capital income and the 30/34% bracket position."""
    sales, excluded_ost_sales = _taxable_gains_for_year(txns, year)
    dividends, excluded_ost_div, _ = _dividends_for_year(txns, year)

    taxable_gains = sum((s.gain_eur for s in sales), Decimal("0"))
    gross_div = sum((d.gross_eur for d in dividends), Decimal("0"))
    taxable_div = sum((d.taxable_eur for d in dividends), Decimal("0"))

    combined = taxable_gains + taxable_div
    tax, eff = tax_math.capital_gains_tax(combined)
    threshold = tax_math.BRACKET_THRESHOLD
    positive_combined = combined if combined > 0 else Decimal("0")
    remaining = max(Decimal("0"), threshold - positive_combined)
    over = max(Decimal("0"), combined - threshold)

    return CapitalIncomeSummary(
        year=year,
        taxable_gains_eur=taxable_gains,
        gross_dividends_eur=gross_div,
        taxable_dividends_eur=taxable_div,
        combined_taxable_eur=combined,
        bracket_threshold_eur=threshold,
        remaining_at_low_rate_eur=remaining,
        amount_over_threshold_eur=over,
        estimated_tax_eur=tax,
        effective_rate=eff,
        low_rate=tax_math.LOW_TAX_RATE,
        high_rate=tax_math.HIGH_TAX_RATE,
        sale_count=len(sales),
        dividend_payment_count=sum(d.payments for d in dividends),
        sales=sales,
        dividends=dividends,
        excluded_ost_dividends_eur=excluded_ost_div,
        excluded_ost_sale_count=excluded_ost_sales,
    )
