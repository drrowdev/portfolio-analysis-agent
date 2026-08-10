from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.analysis import (
    AnalysisSnapshot,
    GuidanceAction,
    GuidanceBrief,
    GuidanceException,
    GuidanceHealth,
    GuidancePassiveBaseline,
    GuidanceTaxCostFacts,
)
from app.services.analysis_snapshot import build_analysis_snapshot


_ISSUE_TITLES = {
    "policy_incomplete": "Complete the investment settings",
    "portfolio_empty": "Add portfolio data",
    "invalid_cash_setting": "Correct the cash balance",
    "missing_ost_deposits": "Add OST deposit history",
    "missing_market_prices": "Refresh missing market prices",
    "stale_market_prices": "Refresh stale market prices",
    "missing_price_timestamp": "Verify price timestamps",
    "missing_sector_metadata": "Complete holding classifications",
    "unverified_transaction_fx": "Verify historical exchange rates",
    "invalid_transaction_eur_basis": "Correct transaction values",
    "incomplete_tax_lots": "Reconcile FIFO acquisition history",
    "missing_strategy": "Configure one investment strategy",
    "multiple_active_strategies": "Choose one active strategy",
    "performance_warning": "Resolve the performance-data warning",
    "performance_scope_incomplete": "Complete the benchmark scope",
    "performance_unavailable": "Restore benchmark performance data",
}


def _issue_title(code: str) -> str:
    return _ISSUE_TITLES.get(code, code.replace("_", " ").capitalize())


def _tax_cost_detail(snapshot: AnalysisSnapshot) -> str:
    capital_income = snapshot.capital_income
    if capital_income.amount_over_threshold_eur > 0:
        bracket_detail = (
            "Tracked taxable capital income exceeds the €30,000 lower-rate band."
        )
    else:
        bracket_detail = (
            "Tracked taxable capital income remains within the €30,000 lower-rate "
            "band."
        )
    return (
        f"{bracket_detail} No tax- or fee-saving action has been quantified. "
        "Untracked income, foreign withholding credits, and future OST withdrawal "
        "tax are excluded."
    )


def build_guidance_brief(snapshot: AnalysisSnapshot) -> GuidanceBrief:
    """Build the no-action-biased consumer brief from deterministic facts only."""
    blocking_issue = next(
        (
            issue
            for issue in snapshot.data_quality.issues
            if issue.severity == "blocking"
        ),
        None,
    )
    breached_signal = next(
        (
            signal
            for signal in snapshot.baselines.signals
            if signal.status == "breach"
        ),
        None,
    )

    if blocking_issue is not None:
        health = GuidanceHealth(
            status="blocked",
            title="Data needs attention",
            detail=blocking_issue.message,
        )
        action = GuidanceAction(
            status="blocked",
            decision="abstain",
            title="Fix the inputs before acting",
            detail=(
                f"{blocking_issue.message} No portfolio change is supported until "
                "the portfolio checks can run on reliable data."
            ),
            origin="rule",
            provenance=blocking_issue.code,
            as_of=snapshot.as_of,
        )
    elif breached_signal is not None:
        health = GuidanceHealth(
            status="review",
            title="A risk limit needs review",
            detail=breached_signal.message,
        )
        action = GuidanceAction(
            status="review",
            decision="hold",
            title="Review the guardrail; do not trade yet",
            detail=(
                f"{breached_signal.message} A sale could create immediate tax and "
                "transaction-cost drag, so no trade is recommended without evidence "
                "that the after-tax benefit exceeds that drag."
            ),
            origin="rule",
            provenance=breached_signal.code,
            as_of=snapshot.as_of,
        )
    else:
        health = GuidanceHealth(
            status="on_track",
            title="Within the configured guardrails",
            detail="No data-quality or portfolio-risk limit is breached.",
        )
        action = GuidanceAction(
            status="no_action",
            decision="hold",
            title="No action needed",
            detail=(
                "No validated return-seeking strategy supports a portfolio change. "
                "Avoiding unnecessary turnover preserves capital and defers tax."
            ),
            origin="rule",
            provenance="no_validated_return_seeking_candidate",
            as_of=snapshot.as_of,
        )

    current_exceptions = [
        GuidanceException(
            code=issue.code,
            severity=issue.severity,
            title=_issue_title(issue.code),
            detail=issue.message,
        )
        for issue in snapshot.data_quality.issues
    ]
    current_exceptions.extend(
        GuidanceException(
            code=signal.code,
            severity="warning",
            title="Configured risk limit breached",
            detail=signal.message,
        )
        for signal in snapshot.baselines.signals
        if signal.status == "breach"
    )

    performance = snapshot.metrics.performance
    passive_baseline = GuidancePassiveBaseline(
        period=performance.period if performance is not None else "1y",
        index_name=snapshot.policy.benchmark_name,
        index_ticker=snapshot.policy.benchmark_ticker,
        currency=snapshot.policy.benchmark_currency,
        status=(
            "available"
            if performance is not None
            and performance.portfolio_return_pct is not None
            and performance.benchmark_return_pct is not None
            else "unavailable"
        ),
        portfolio_return_pct=(
            performance.portfolio_return_pct if performance is not None else None
        ),
        index_return_pct=(
            performance.benchmark_return_pct if performance is not None else None
        ),
        active_return_pct=(
            performance.active_return_pct if performance is not None else None
        ),
        comparison_basis=(
            "Equity-only time-weighted market return in EUR using total-return "
            "price relatives."
        ),
        excluded_from_comparison=["cash", "transaction fees", "taxes"],
        investable_comparator_status="not_configured",
        investable_comparator_message=(
            "No investable accumulating-ETF comparator is configured. The index is "
            "not directly investable, and ETFs cannot be held in a Finnish OST. "
            "No after-tax ETF result is inferred."
        ),
    )

    turnover = snapshot.metrics.turnover
    tax_and_cost = GuidanceTaxCostFacts(
        year=snapshot.capital_income.year,
        tracked_taxable_income_eur=snapshot.capital_income.combined_taxable_eur,
        estimated_tax_eur=snapshot.capital_income.estimated_tax_eur,
        remaining_at_low_rate_eur=snapshot.capital_income.remaining_at_low_rate_eur,
        amount_over_threshold_eur=snapshot.capital_income.amount_over_threshold_eur,
        ytd_turnover_pct=turnover.ytd_turnover_pct if turnover is not None else None,
        transaction_cost_assumption_bps=(
            snapshot.policy.estimated_transaction_cost_bps
        ),
        detail=_tax_cost_detail(snapshot),
    )

    return GuidanceBrief(
        as_of=snapshot.as_of,
        snapshot_hash=snapshot.snapshot_hash,
        health=health,
        best_action=action,
        current_exceptions=current_exceptions,
        tax_and_cost=tax_and_cost,
        passive_baseline=passive_baseline,
        snapshot=snapshot,
        disclaimer=(
            "Informational only, not financial advice. Tax estimates use recorded "
            "transactions and may omit other taxable income."
        ),
    )


async def build_guidance(db: AsyncSession) -> GuidanceBrief:
    snapshot = await build_analysis_snapshot(db)
    return build_guidance_brief(snapshot)
