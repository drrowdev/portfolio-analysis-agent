"""Deterministic shadow candidates for enforcing explicit portfolio risk limits."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_UP

from app.schemas.analysis import (
    AccountSnapshot,
    AnalysisRecommendation,
    AnalysisSnapshot,
    CandidateGenerationResult,
    HoldingSnapshot,
)
from app.services import tax as tax_math


_ZERO = Decimal("0")
_ONE = Decimal("1")
_HUNDRED = Decimal("100")
_MONEY = Decimal("0.01")
_QUANTITY = Decimal("0.000001")
_WEIGHT_TOLERANCE = Decimal("0.01")
_METHOD = (
    "Risk-only shadow policy: maximize invested value subject to the explicit "
    "single-position and sector caps, direct gross sale proceeds to cash, choose "
    "supported account lots by estimated tax drag, and reject the plan if current "
    "plus proposed gross YTD turnover exceeds its limit. No return or alpha "
    "forecast is made. Historical drawdown, volatility, and tracking-error "
    "breaches require marginal-risk inputs and cannot create a trade in this phase."
)


@dataclass
class _HoldingPlan:
    holding: HoldingSnapshot
    account: AccountSnapshot
    value_eur: Decimal
    tax_drag_ratio: Decimal | None
    planned_sale_eur: Decimal = _ZERO

    @property
    def available_eur(self) -> Decimal:
        return max(_ZERO, self.value_eur - self.planned_sale_eur)


def _result(
    snapshot: AnalysisSnapshot,
    *,
    status: str,
    issues: list[str],
    recommendations: list[AnalysisRecommendation] | None = None,
    projected_invested_value_eur: Decimal | None = None,
    projected_turnover_pct: Decimal | None = None,
) -> CandidateGenerationResult:
    turnover = snapshot.metrics.turnover
    return CandidateGenerationResult(
        status=status,
        recommendations=recommendations or [],
        issues=issues,
        current_invested_value_eur=snapshot.invested_value_eur,
        projected_invested_value_eur=(
            projected_invested_value_eur
            if projected_invested_value_eur is not None
            else snapshot.invested_value_eur
        ),
        current_ytd_turnover_pct=(
            turnover.ytd_turnover_pct if turnover is not None else None
        ),
        projected_ytd_turnover_pct=projected_turnover_pct,
        methodology=_METHOD,
    )


def _tax_lots(
    snapshot: AnalysisSnapshot,
    holding: HoldingSnapshot,
    quantity: Decimal,
) -> list[tax_math.TaxLot] | None:
    remaining = quantity
    lots: list[tax_math.TaxLot] = []
    for lot in snapshot.open_tax_lots:
        if lot.account_id != holding.account_id or lot.symbol != holding.symbol:
            continue
        take = min(remaining, lot.quantity)
        if take > 0:
            lots.append(
                tax_math.TaxLot(
                    quantity=take,
                    cost_per_share_eur=lot.cost_per_share_eur,
                    over_10_years=tax_math.held_at_least_10_years(
                        lot.purchase_date,
                        snapshot.as_of.date(),
                    ),
                )
            )
            remaining -= take
        if remaining <= 0:
            break
    return lots if remaining <= 0 else None


def _tax_estimate(
    snapshot: AnalysisSnapshot,
    plan: _HoldingPlan,
    quantity: Decimal,
    transaction_cost_eur: Decimal,
    prior_income_eur: Decimal,
) -> tuple[Decimal, Decimal] | None:
    if plan.account.tax_treatment == "deferred":
        return _ZERO, _ZERO
    if plan.account.tax_treatment == "espp":
        return None
    lots = _tax_lots(snapshot, plan.holding, quantity)
    if lots is None or plan.holding.current_price_eur is None:
        return None
    result = tax_math.compute(
        lots,
        plan.holding.current_price_eur,
        transaction_cost_eur,
        quantity,
        prior_income_eur,
    )
    if result.shortfall_qty > 0:
        return None
    return result.tax_eur, result.optimum_gain_eur


def _preview_tax_drag(
    snapshot: AnalysisSnapshot,
    holding: HoldingSnapshot,
    account: AccountSnapshot,
) -> Decimal | None:
    if holding.current_value_eur is None or holding.current_value_eur <= 0:
        return None
    provisional = _HoldingPlan(
        holding=holding,
        account=account,
        value_eur=holding.current_value_eur,
        tax_drag_ratio=None,
    )
    transaction_bps = snapshot.policy.estimated_transaction_cost_bps
    if transaction_bps is None:
        return None
    cost = holding.current_value_eur * transaction_bps / Decimal("10000")
    estimate = _tax_estimate(
        snapshot,
        provisional,
        holding.quantity,
        cost,
        snapshot.capital_income.combined_taxable_eur,
    )
    if estimate is None:
        return None
    tax, _ = estimate
    return (tax + cost) / holding.current_value_eur


def _allocate_sale(
    amount_eur: Decimal,
    plans: list[_HoldingPlan],
) -> Decimal:
    remaining = amount_eur
    eligible = sorted(
        (plan for plan in plans if plan.tax_drag_ratio is not None),
        key=lambda plan: (
            plan.tax_drag_ratio,
            plan.holding.symbol,
            plan.holding.account_id,
        ),
    )
    for plan in eligible:
        take = min(remaining, plan.available_eur)
        if take <= 0:
            continue
        plan.planned_sale_eur += take
        remaining -= take
        if remaining <= Decimal("0.000001"):
            return _ZERO
    return max(_ZERO, remaining)


def _retention_capacity(
    target_invested_eur: Decimal,
    symbol_values: dict[str, Decimal],
    symbol_sectors: dict[str, str],
    position_limit: Decimal,
    sector_limit: Decimal,
) -> Decimal:
    sector_capacity: dict[str, Decimal] = {}
    for symbol, value in symbol_values.items():
        sector = symbol_sectors[symbol]
        symbol_capacity = min(value, position_limit * target_invested_eur)
        sector_capacity[sector] = sector_capacity.get(sector, _ZERO) + symbol_capacity
    return sum(
        (
            min(value, sector_limit * target_invested_eur)
            for value in sector_capacity.values()
        ),
        _ZERO,
    )


def _maximum_feasible_invested_value(
    invested_value_eur: Decimal,
    symbol_values: dict[str, Decimal],
    symbol_sectors: dict[str, str],
    position_limit: Decimal,
    sector_limit: Decimal,
) -> Decimal:
    if (
        _retention_capacity(
            invested_value_eur,
            symbol_values,
            symbol_sectors,
            position_limit,
            sector_limit,
        )
        >= invested_value_eur
    ):
        return invested_value_eur

    low = _ZERO
    high = invested_value_eur
    for _ in range(100):
        midpoint = (low + high) / 2
        capacity = _retention_capacity(
            midpoint,
            symbol_values,
            symbol_sectors,
            position_limit,
            sector_limit,
        )
        if capacity >= midpoint:
            low = midpoint
        else:
            high = midpoint
    return low


def _projected_turnover_pct(
    snapshot: AnalysisSnapshot,
    proposed_notional_eur: Decimal,
) -> Decimal | None:
    turnover = snapshot.metrics.turnover
    if turnover is None or snapshot.total_portfolio_value_eur <= 0:
        return None
    return (
        (turnover.traded_notional_eur + proposed_notional_eur)
        / snapshot.total_portfolio_value_eur
        * _HUNDRED
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def generate_risk_enforcement_candidates(
    snapshot: AnalysisSnapshot,
) -> CandidateGenerationResult:
    """Generate tax-aware shadow sells for concentration-limit enforcement."""
    if not snapshot.data_quality.can_recommend_trades:
        return _result(
            snapshot,
            status="blocked",
            issues=["Snapshot data quality blocks deterministic candidates."],
        )

    unsupported_breaches = {
        signal.code
        for signal in snapshot.baselines.signals
        if signal.status == "breach"
        and signal.code
        in {"drawdown_limit", "volatility_limit", "tracking_error_limit"}
    }
    if unsupported_breaches:
        return _result(
            snapshot,
            status="blocked",
            issues=[
                "Unsupported risk breaches require marginal-risk calculations: "
                + ", ".join(sorted(unsupported_breaches))
            ],
        )

    policy = snapshot.policy
    if (
        policy.max_single_position_pct is None
        or policy.max_sector_pct is None
        or policy.max_annual_turnover_pct is None
        or policy.estimated_transaction_cost_bps is None
    ):
        return _result(
            snapshot,
            status="blocked",
            issues=["Risk, turnover, and transaction-cost limits must be explicit."],
        )
    if snapshot.metrics.turnover is None:
        return _result(
            snapshot,
            status="blocked",
            issues=["Current year-to-date turnover is unavailable."],
        )

    invested = snapshot.invested_value_eur
    if invested <= 0:
        return _result(snapshot, status="no_action", issues=[])

    accounts = {account.id: account for account in snapshot.accounts}
    holdings = [
        holding
        for holding in snapshot.holdings
        if holding.quantity > 0
        and holding.current_value_eur is not None
        and holding.current_value_eur > 0
        and holding.current_price_eur is not None
        and holding.current_price_eur > 0
        and holding.sector is not None
        and holding.account_id in accounts
    ]
    if not holdings:
        return _result(
            snapshot,
            status="blocked",
            issues=["No fully valued, sector-classified holdings are available."],
        )

    symbol_values: dict[str, Decimal] = {}
    symbol_sectors: dict[str, str] = {}
    for holding in holdings:
        assert holding.current_value_eur is not None
        symbol_values[holding.symbol] = (
            symbol_values.get(holding.symbol, _ZERO) + holding.current_value_eur
        )
        existing_sector = symbol_sectors.setdefault(holding.symbol, holding.sector or "")
        if existing_sector != holding.sector:
            return _result(
                snapshot,
                status="blocked",
                issues=[f"{holding.symbol} has inconsistent sector metadata."],
            )

    position_limit = policy.max_single_position_pct / _HUNDRED
    sector_limit = policy.max_sector_pct / _HUNDRED
    target_invested = _maximum_feasible_invested_value(
        invested,
        symbol_values,
        symbol_sectors,
        position_limit,
        sector_limit,
    )
    if target_invested >= invested - Decimal("0.000001"):
        return _result(
            snapshot,
            status="no_action",
            issues=[],
            projected_turnover_pct=snapshot.metrics.turnover.ytd_turnover_pct,
        )
    if target_invested <= _MONEY:
        return _result(
            snapshot,
            status="blocked",
            issues=[
                "The configured concentration limits are infeasible for the "
                "current number of symbols or sectors without effectively "
                "liquidating the invested portfolio."
            ],
        )

    plans = [
        _HoldingPlan(
            holding=holding,
            account=accounts[holding.account_id],
            value_eur=holding.current_value_eur or _ZERO,
            tax_drag_ratio=_preview_tax_drag(
                snapshot,
                holding,
                accounts[holding.account_id],
            ),
        )
        for holding in holdings
    ]

    for symbol, value in sorted(symbol_values.items()):
        required = max(_ZERO, value - position_limit * target_invested)
        if required <= 0:
            continue
        remaining = _allocate_sale(
            required,
            [plan for plan in plans if plan.holding.symbol == symbol],
        )
        if remaining > _MONEY:
            return _result(
                snapshot,
                status="blocked",
                issues=[
                    f"{symbol} cannot be reduced to its position limit with "
                    "supported, reconciled tax lots."
                ],
            )

    for sector in sorted(set(symbol_sectors.values())):
        retained = sum(
            (
                plan.value_eur - plan.planned_sale_eur
                for plan in plans
                if plan.holding.sector == sector
            ),
            _ZERO,
        )
        required = max(_ZERO, retained - sector_limit * target_invested)
        if required <= 0:
            continue
        remaining = _allocate_sale(
            required,
            [plan for plan in plans if plan.holding.sector == sector],
        )
        if remaining > _MONEY:
            return _result(
                snapshot,
                status="blocked",
                issues=[
                    f"{sector} cannot be reduced to its sector limit with "
                    "supported, reconciled tax lots."
                ],
            )

    retained = invested - sum(
        (plan.planned_sale_eur for plan in plans),
        _ZERO,
    )
    remaining = _allocate_sale(max(_ZERO, retained - target_invested), plans)
    if remaining > _MONEY:
        return _result(
            snapshot,
            status="blocked",
            issues=["The risk-constrained retention plan could not be allocated."],
        )

    planned = [plan for plan in plans if plan.planned_sale_eur > _MONEY]
    actual_sales: list[tuple[_HoldingPlan, Decimal, Decimal]] = []
    for plan in planned:
        price = plan.holding.current_price_eur
        if price is None or price <= 0:
            return _result(
                snapshot,
                status="blocked",
                issues=[f"{plan.holding.symbol} has no usable reference price."],
            )
        quantity = min(
            plan.holding.quantity,
            (plan.planned_sale_eur / price).quantize(
                _QUANTITY,
                rounding=ROUND_UP,
            ),
        )
        amount = quantity * price
        actual_sales.append((plan, quantity, amount))

    total_sale = sum((amount for _, _, amount in actual_sales), _ZERO)
    projected_turnover = _projected_turnover_pct(snapshot, total_sale)
    if projected_turnover is None:
        return _result(
            snapshot,
            status="blocked",
            issues=["Projected turnover cannot be calculated."],
        )
    if projected_turnover > policy.max_annual_turnover_pct:
        return _result(
            snapshot,
            status="blocked",
            issues=[
                f"Risk enforcement would raise gross YTD turnover to "
                f"{projected_turnover}%, above the "
                f"{policy.max_annual_turnover_pct}% limit."
            ],
            projected_turnover_pct=projected_turnover,
        )

    projected_invested = invested - total_sale
    projected_symbols = dict(symbol_values)
    projected_sectors: dict[str, Decimal] = {}
    for plan, _, amount in actual_sales:
        projected_symbols[plan.holding.symbol] -= amount
    for symbol, value in projected_symbols.items():
        sector = symbol_sectors[symbol]
        projected_sectors[sector] = projected_sectors.get(sector, _ZERO) + value

    if projected_invested <= 0:
        return _result(
            snapshot,
            status="blocked",
            issues=["The candidate plan would liquidate the invested portfolio."],
        )
    position_breaches = [
        symbol
        for symbol, value in projected_symbols.items()
        if value / projected_invested * _HUNDRED
        > policy.max_single_position_pct + _WEIGHT_TOLERANCE
    ]
    sector_breaches = [
        sector
        for sector, value in projected_sectors.items()
        if value / projected_invested * _HUNDRED
        > policy.max_sector_pct + _WEIGHT_TOLERANCE
    ]
    if position_breaches or sector_breaches:
        return _result(
            snapshot,
            status="blocked",
            issues=[
                "Rounded candidate quantities do not satisfy all concentration "
                "limits; no partial plan was emitted."
            ],
        )

    group_material = (
        f"{snapshot.snapshot_hash}:{projected_invested}:{total_sale}"
    ).encode("utf-8")
    group_id = "risk-" + hashlib.sha256(group_material).hexdigest()[:16]
    prior_income = snapshot.capital_income.combined_taxable_eur
    recommendations: list[AnalysisRecommendation] = []
    for plan, quantity, amount in actual_sales:
        cost = (
            amount
            * policy.estimated_transaction_cost_bps
            / Decimal("10000")
        ).quantize(_MONEY, rounding=ROUND_HALF_UP)
        estimate = _tax_estimate(
            snapshot,
            plan,
            quantity,
            cost,
            prior_income,
        )
        if estimate is None:
            return _result(
                snapshot,
                status="blocked",
                issues=[
                    f"Tax impact could not be reproduced for "
                    f"{plan.holding.symbol} in {plan.account.name}."
                ],
            )
        tax, gain = estimate
        prior_income += gain
        candidate_material = (
            f"{group_id}:{plan.holding.account_id}:{plan.holding.symbol}:"
            f"{quantity}:{amount}"
        ).encode("utf-8")
        candidate_id = "candidate-" + hashlib.sha256(
            candidate_material
        ).hexdigest()[:16]
        symbol_weight = (
            projected_symbols[plan.holding.symbol]
            / projected_invested
            * _HUNDRED
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        sector = plan.holding.sector or "Unknown"
        sector_weight = (
            projected_sectors[sector] / projected_invested * _HUNDRED
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        recommendations.append(
            AnalysisRecommendation(
                action=(
                    f"Shadow sell {format(quantity.normalize(), 'f')} "
                    f"{plan.holding.symbol} and retain proceeds as cash"
                ),
                rationale=(
                    "This deterministic candidate exists only to enforce explicit "
                    "concentration limits. It makes no expected-return or alpha claim."
                ),
                account_type=plan.account.account_type,
                priority="high",
                decision="sell",
                confidence="high",
                urgency="soon",
                candidate_id=candidate_id,
                candidate_group_id=group_id,
                candidate_objective="risk_enforcement",
                symbol=plan.holding.symbol,
                account_id=plan.holding.account_id,
                quantity=quantity,
                amount_eur=amount,
                timeframe=(
                    "Next available market close before the candidate expires"
                ),
                valid_until=snapshot.as_of.date() + timedelta(days=7),
                estimated_transaction_cost_eur=cost,
                estimated_tax_impact_eur=tax.quantize(
                    _MONEY,
                    rounding=ROUND_HALF_UP,
                ),
                risk_impact=(
                    f"Combined plan projects {plan.holding.symbol} at "
                    f"{symbol_weight}% and {sector} at {sector_weight}% of "
                    f"remaining invested assets."
                ),
                reference_price_eur=plan.holding.current_price_eur,
                currency=plan.holding.currency,
                execution_assumption="cash",
                trigger_conditions=[
                    (
                        "Current single-position or sector concentration exceeds "
                        "an explicit policy maximum."
                    )
                ],
                assumptions=[
                    "Gross proceeds remain in cash.",
                    "No return, downside, or alpha forecast is made.",
                    (
                        "Tax impact uses recorded FIFO lots, Finnish deemed-cost "
                        "rules, and current YTD capital income."
                    ),
                    (
                        "Transaction cost uses the policy basis-point estimate; "
                        "market impact and slippage beyond that estimate are excluded."
                    ),
                ],
                evidence=[
                    "deterministic_risk_enforcement",
                    "single_position_and_sector_caps",
                    "fifo_tax_estimate",
                    "ytd_turnover_limit",
                ],
            )
        )

    return _result(
        snapshot,
        status="candidates",
        issues=[],
        recommendations=recommendations,
        projected_invested_value_eur=projected_invested,
        projected_turnover_pct=projected_turnover,
    )
