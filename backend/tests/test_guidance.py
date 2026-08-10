from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.analysis import (
    AnalysisMetrics,
    AnalysisSnapshot,
    CapitalIncomeSnapshot,
    DataQualityIssue,
    DataQualityState,
    GuidanceAction,
    PerformanceRiskMetrics,
    ProofOfValuePolicy,
    TurnoverMetrics,
)
from app.services.analysis_baselines import evaluate_baselines
from app.services.analysis_metrics import (
    calculate_concentration,
    calculate_sector_exposure,
)
from app.services.guidance import build_guidance_brief
from app.services.proof_of_value import _policy_state


def _snapshot(
    *,
    max_position_pct: str = "90",
    issues: list[DataQualityIssue] | None = None,
) -> AnalysisSnapshot:
    policy = _policy_state(
        ProofOfValuePolicy(
            investment_horizon_years=5,
            max_drawdown_pct=Decimal("25"),
            max_annualized_volatility_pct=Decimal("20"),
            max_tracking_error_pct=Decimal("10"),
            max_single_position_pct=Decimal(max_position_pct),
            max_sector_pct=Decimal("90"),
            max_annual_turnover_pct=Decimal("50"),
            estimated_transaction_cost_bps=Decimal("20"),
            minimum_expected_net_alpha_pct=Decimal("2"),
        )
    )
    metrics = AnalysisMetrics(
        performance=PerformanceRiskMetrics(
            period="1y",
            observations=250,
            portfolio_return_pct=8.0,
            benchmark_return_pct=10.0,
            active_return_pct=-2.0,
            annualized_volatility_pct=12.0,
            benchmark_annualized_volatility_pct=14.0,
            tracking_error_pct=5.0,
            beta=0.9,
            max_drawdown_pct=10.0,
            benchmark_max_drawdown_pct=12.0,
        ),
        concentration=calculate_concentration(
            [("CONCENTRATED", Decimal("80")), ("OTHER", Decimal("20"))]
        ),
        sectors=calculate_sector_exposure(
            {"Technology": Decimal("80"), "Other": Decimal("20")},
            Decimal("100"),
        ),
        turnover=TurnoverMetrics(
            year=2026,
            traded_notional_eur=Decimal("10"),
            portfolio_value_eur=Decimal("100"),
            ytd_turnover_pct=Decimal("10"),
            methodology="test",
        ),
    )
    return AnalysisSnapshot(
        as_of=datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc),
        snapshot_hash="a" * 64,
        policy=policy,
        data_quality=DataQualityState(
            can_recommend_trades=not issues,
            issues=issues or [],
        ),
        cash_eur=Decimal("0"),
        invested_value_eur=Decimal("100"),
        total_portfolio_value_eur=Decimal("100"),
        accounts=[],
        holdings=[],
        open_tax_lots=[],
        capital_income=CapitalIncomeSnapshot(
            year=2026,
            taxable_gains_eur=Decimal("10000"),
            taxable_dividends_eur=Decimal("1000"),
            combined_taxable_eur=Decimal("11000"),
            estimated_tax_eur=Decimal("3300"),
            remaining_at_low_rate_eur=Decimal("19000"),
            amount_over_threshold_eur=Decimal("0"),
        ),
        strategy=None,
        goals=[],
        metrics=metrics,
        baselines=evaluate_baselines(policy, metrics),
    )


def test_guidance_blocks_actions_when_inputs_are_unreliable():
    guidance = build_guidance_brief(
        _snapshot(
            issues=[
                DataQualityIssue(
                    code="incomplete_tax_lots",
                    severity="blocking",
                    message="FIFO acquisition history does not reconcile.",
                )
            ]
        )
    )

    assert guidance.health.status == "blocked"
    assert guidance.best_action.decision == "abstain"
    assert guidance.best_action.origin == "rule"
    assert guidance.current_exceptions[0].code == "incomplete_tax_lots"
    assert guidance.passive_baseline.investable_comparator_status == "not_configured"
    assert "taxes" in guidance.passive_baseline.excluded_from_comparison


def test_guidance_keeps_a_risk_breach_informational():
    guidance = build_guidance_brief(_snapshot(max_position_pct="50"))

    assert guidance.health.status == "review"
    assert guidance.best_action.status == "review"
    assert guidance.best_action.decision == "hold"
    assert "no trade is recommended" in guidance.best_action.detail
    assert guidance.best_action.provenance == "single_position_limit"


def test_guidance_defaults_to_no_action_even_when_trailing_the_index():
    guidance = build_guidance_brief(_snapshot())

    assert guidance.health.status == "on_track"
    assert guidance.best_action.status == "no_action"
    assert guidance.best_action.title == "No action needed"
    assert guidance.passive_baseline.active_return_pct == pytest.approx(-2.0)
    assert guidance.tax_and_cost.estimated_tax_eur == Decimal("3300")
    assert guidance.tax_and_cost.quantified_savings_eur is None


def test_guidance_action_schema_rejects_ai_as_an_origin():
    with pytest.raises(ValidationError):
        GuidanceAction.model_validate(
            {
                "status": "no_action",
                "decision": "hold",
                "title": "Do nothing",
                "detail": "AI must not control this field.",
                "origin": "ai",
                "provenance": "model",
                "as_of": "2026-08-10T12:00:00Z",
            }
        )
