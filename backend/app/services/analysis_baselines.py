from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from app.schemas.analysis import (
    AnalysisMetrics,
    BaselineComparison,
    BaselineSignal,
    ProofOfValuePolicyState,
)


_PCT = Decimal("0.01")


def _decimal(value: float | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(_PCT, rounding=ROUND_HALF_UP)


def _limit_signal(
    *,
    code: str,
    label: str,
    metric: Decimal | None,
    limit: Decimal | None,
) -> BaselineSignal:
    if metric is None or limit is None:
        return BaselineSignal(
            code=code,
            status="unavailable",
            metric_value=metric,
            policy_limit=limit,
            message=f"{label} cannot be evaluated until both metric and limit exist.",
        )
    breached = metric > limit
    return BaselineSignal(
        code=code,
        status="breach" if breached else "pass",
        metric_value=metric,
        policy_limit=limit,
        message=(
            f"{label} is {metric}% against a {limit}% maximum."
            if breached
            else f"{label} remains within its {limit}% maximum."
        ),
    )


def evaluate_baselines(
    policy: ProofOfValuePolicyState,
    metrics: AnalysisMetrics,
) -> BaselineComparison:
    """Compare observed hold/benchmark returns and evaluate the rules-only policy."""
    performance = metrics.performance
    sector_data_complete = all(
        exposure.sector != "Unknown" for exposure in metrics.sectors
    )
    signals = [
        _limit_signal(
            code="single_position_limit",
            label="Largest position",
            metric=metrics.concentration.largest_position_pct,
            limit=policy.max_single_position_pct,
        ),
        _limit_signal(
            code="sector_limit",
            label="Largest sector",
            metric=(
                metrics.sectors[0].weight_pct
                if metrics.sectors and sector_data_complete
                else None
            ),
            limit=policy.max_sector_pct,
        ),
        _limit_signal(
            code="drawdown_limit",
            label="Observed maximum drawdown",
            metric=(
                _decimal(performance.max_drawdown_pct)
                if performance is not None
                else None
            ),
            limit=policy.max_drawdown_pct,
        ),
        _limit_signal(
            code="volatility_limit",
            label="Observed annualized volatility",
            metric=(
                _decimal(performance.annualized_volatility_pct)
                if performance is not None
                else None
            ),
            limit=policy.max_annualized_volatility_pct,
        ),
        _limit_signal(
            code="tracking_error_limit",
            label="Observed tracking error",
            metric=(
                _decimal(performance.tracking_error_pct)
                if performance is not None
                else None
            ),
            limit=policy.max_tracking_error_pct,
        ),
        BaselineSignal(
            code="turnover_limit",
            status=(
                "unavailable"
                if metrics.turnover is None
                or metrics.turnover.ytd_turnover_pct is None
                or policy.max_annual_turnover_pct is None
                else (
                    "breach"
                    if metrics.turnover.ytd_turnover_pct
                    > policy.max_annual_turnover_pct
                    else "pass"
                )
            ),
            metric_value=(
                metrics.turnover.ytd_turnover_pct
                if metrics.turnover is not None
                else None
            ),
            policy_limit=policy.max_annual_turnover_pct,
            message=(
                "Gross year-to-date turnover is "
                f"{metrics.turnover.ytd_turnover_pct}% against a "
                f"{policy.max_annual_turnover_pct}% maximum."
                if metrics.turnover is not None
                and metrics.turnover.ytd_turnover_pct is not None
                and policy.max_annual_turnover_pct is not None
                else "Turnover cannot be evaluated until metric and limit exist."
            ),
        ),
    ]
    if not policy.is_complete or performance is None:
        status = "blocked"
    elif any(signal.status == "unavailable" for signal in signals):
        status = "blocked"
    elif any(signal.status == "breach" for signal in signals):
        status = "review_required"
    else:
        status = "within_limits"

    return BaselineComparison(
        hold_current_return_pct=(
            _decimal(performance.portfolio_return_pct)
            if performance is not None
            else None
        ),
        benchmark_return_pct=(
            _decimal(performance.benchmark_return_pct)
            if performance is not None
            else None
        ),
        historical_active_return_pct=(
            _decimal(performance.active_return_pct)
            if performance is not None
            else None
        ),
        deterministic_policy_status=status,
        signals=signals,
        methodology=(
            "The hold-current and benchmark values are observed one-year returns, "
            "not forecasts. The deterministic comparator only checks explicit risk "
            "thresholds. Risk-enforcement candidates may be generated without an "
            "alpha forecast; return-seeking trades remain disabled until expected "
            "net alpha can be computed reproducibly."
        ),
    )
