from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.analysis import (
    AccountSnapshot,
    AnalysisMetrics,
    AnalysisRecommendation,
    AnalysisSnapshot,
    CapitalIncomeSnapshot,
    DataQualityState,
    HoldingSnapshot,
    OpenTaxLotSnapshot,
    TurnoverMetrics,
)
from app.services.analysis_baselines import evaluate_baselines
from app.services.analysis_candidates import generate_risk_enforcement_candidates
from app.services.analysis_metrics import (
    calculate_concentration,
    calculate_sector_exposure,
)
from app.services.proof_of_value import _policy_state
from app.schemas.analysis import ProofOfValuePolicy


def _account(account_id: str, treatment: str) -> AccountSnapshot:
    return AccountSnapshot(
        id=account_id,
        name=account_id,
        account_type="osakesaastotili" if treatment == "deferred" else "arvo_osuustili",
        tax_treatment=treatment,
        currency="EUR",
        ost_lifetime_deposits_eur=Decimal("1000") if treatment == "deferred" else None,
        market_value_eur=Decimal("0"),
        cost_basis_eur=Decimal("0"),
    )


def _holding(
    *,
    account_id: str,
    symbol: str,
    sector: str,
    value: str,
    price: str = "10",
) -> HoldingSnapshot:
    value_eur = Decimal(value)
    price_eur = Decimal(price)
    return HoldingSnapshot(
        account_id=account_id,
        account_name=account_id,
        account_type="brokerage",
        tax_treatment="deferred",
        symbol=symbol,
        instrument_name=symbol,
        currency="EUR",
        quantity=value_eur / price_eur,
        cost_basis_eur=value_eur,
        current_price_eur=price_eur,
        current_value_eur=value_eur,
        unrealized_pnl_eur=Decimal("0"),
        unrealized_pnl_pct=Decimal("0"),
        portfolio_weight_pct=value_eur,
        sector=sector,
        industry=sector,
        country="FI",
        price_as_of=datetime(2026, 8, 7, tzinfo=timezone.utc),
    )


def _snapshot(
    *,
    accounts: list[AccountSnapshot],
    holdings: list[HoldingSnapshot],
    lots: list[OpenTaxLotSnapshot] | None = None,
    max_position_pct: str = "60",
    max_sector_pct: str = "100",
    max_turnover_pct: str = "100",
    transaction_cost_bps: str = "0",
) -> AnalysisSnapshot:
    invested = sum(
        (holding.current_value_eur or Decimal("0") for holding in holdings),
        Decimal("0"),
    )
    symbol_values: dict[str, Decimal] = {}
    sector_values: dict[str, Decimal] = {}
    for holding in holdings:
        value = holding.current_value_eur or Decimal("0")
        symbol_values[holding.symbol] = symbol_values.get(
            holding.symbol, Decimal("0")
        ) + value
        sector_values[holding.sector or "Unknown"] = sector_values.get(
            holding.sector or "Unknown", Decimal("0")
        ) + value

    policy = _policy_state(
        ProofOfValuePolicy(
            investment_horizon_years=5,
            max_drawdown_pct=Decimal("25"),
            max_annualized_volatility_pct=Decimal("30"),
            max_tracking_error_pct=Decimal("20"),
            max_single_position_pct=Decimal(max_position_pct),
            max_sector_pct=Decimal(max_sector_pct),
            max_annual_turnover_pct=Decimal(max_turnover_pct),
            estimated_transaction_cost_bps=Decimal(transaction_cost_bps),
            minimum_expected_net_alpha_pct=Decimal("2"),
        )
    )
    metrics = AnalysisMetrics(
        performance=None,
        concentration=calculate_concentration(list(symbol_values.items())),
        sectors=calculate_sector_exposure(sector_values, invested),
        turnover=TurnoverMetrics(
            year=2026,
            traded_notional_eur=Decimal("0"),
            portfolio_value_eur=invested,
            ytd_turnover_pct=Decimal("0"),
            methodology="test",
        ),
    )
    return AnalysisSnapshot(
        as_of=datetime(2026, 8, 7, tzinfo=timezone.utc),
        snapshot_hash="a" * 64,
        policy=policy,
        data_quality=DataQualityState(can_recommend_trades=True),
        cash_eur=Decimal("0"),
        invested_value_eur=invested,
        total_portfolio_value_eur=invested,
        accounts=accounts,
        holdings=holdings,
        open_tax_lots=lots or [],
        capital_income=CapitalIncomeSnapshot(
            year=2026,
            taxable_gains_eur=Decimal("0"),
            taxable_dividends_eur=Decimal("0"),
            combined_taxable_eur=Decimal("0"),
            estimated_tax_eur=Decimal("0"),
            remaining_at_low_rate_eur=Decimal("30000"),
            amount_over_threshold_eur=Decimal("0"),
        ),
        strategy=None,
        goals=[],
        metrics=metrics,
        baselines=evaluate_baselines(policy, metrics),
    )


def test_risk_engine_sells_only_enough_to_restore_position_limit():
    account = _account("ost", "deferred")
    snapshot = _snapshot(
        accounts=[account],
        holdings=[
            _holding(account_id="ost", symbol="A", sector="Tech", value="80"),
            _holding(account_id="ost", symbol="B", sector="Other", value="20"),
        ],
    )

    generated = generate_risk_enforcement_candidates(snapshot)

    assert generated.status == "candidates"
    assert generated.projected_invested_value_eur == pytest.approx(Decimal("50"))
    assert generated.projected_ytd_turnover_pct == Decimal("50.00")
    assert len(generated.recommendations) == 1
    candidate = generated.recommendations[0]
    assert candidate.symbol == "A"
    assert candidate.quantity == Decimal("5.000000")
    assert candidate.amount_eur == Decimal("50.000000")
    assert candidate.estimated_tax_impact_eur == Decimal("0.00")
    assert candidate.candidate_objective == "risk_enforcement"
    assert candidate.expected_net_alpha_pct is None


def test_risk_engine_prefers_tax_deferred_lots_before_taxable_lots():
    taxable = _account("aot", "standard")
    deferred = _account("ost", "deferred")
    holdings = [
        _holding(account_id="aot", symbol="A", sector="Tech", value="40"),
        _holding(account_id="ost", symbol="A", sector="Tech", value="40"),
        _holding(account_id="aot", symbol="B", sector="Other", value="20"),
    ]
    lots = [
        OpenTaxLotSnapshot(
            account_id="aot",
            symbol="A",
            purchase_date=datetime(2025, 1, 1).date(),
            quantity=Decimal("4"),
            cost_per_share_eur=Decimal("5"),
        )
    ]
    snapshot = _snapshot(
        accounts=[taxable, deferred],
        holdings=holdings,
        lots=lots,
    )

    generated = generate_risk_enforcement_candidates(snapshot)

    assert generated.status == "candidates"
    amounts = {
        candidate.account_id: candidate.amount_eur
        for candidate in generated.recommendations
    }
    assert amounts == {
        "ost": Decimal("40.000000"),
        "aot": Decimal("10.000000"),
    }
    taxable_candidate = next(
        item for item in generated.recommendations if item.account_id == "aot"
    )
    assert taxable_candidate.estimated_tax_impact_eur == Decimal("1.50")


def test_risk_engine_blocks_when_enforcement_conflicts_with_turnover_limit():
    account = _account("ost", "deferred")
    snapshot = _snapshot(
        accounts=[account],
        holdings=[
            _holding(account_id="ost", symbol="A", sector="Tech", value="80"),
            _holding(account_id="ost", symbol="B", sector="Other", value="20"),
        ],
        max_turnover_pct="40",
    )

    generated = generate_risk_enforcement_candidates(snapshot)

    assert generated.status == "blocked"
    assert generated.recommendations == []
    assert "above the 40% limit" in generated.issues[0]


def test_risk_engine_blocks_infeasible_concentration_policy():
    account = _account("ost", "deferred")
    snapshot = _snapshot(
        accounts=[account],
        holdings=[
            _holding(account_id="ost", symbol="A", sector="Tech", value="100"),
        ],
    )

    generated = generate_risk_enforcement_candidates(snapshot)

    assert generated.status == "blocked"
    assert "infeasible" in generated.issues[0]


def test_risk_candidate_rejects_an_invented_alpha_forecast():
    with pytest.raises(ValidationError, match="cannot contain return forecasts"):
        AnalysisRecommendation(
            action="Shadow risk sale",
            rationale="Concentration exceeds the explicit limit.",
            account_type="arvo_osuustili",
            priority="high",
            decision="sell",
            confidence="high",
            urgency="soon",
            candidate_id="candidate-1",
            candidate_group_id="risk-1",
            candidate_objective="risk_enforcement",
            symbol="A",
            account_id="aot",
            quantity=Decimal("1"),
            amount_eur=Decimal("10"),
            timeframe="Next close",
            valid_until=datetime(2026, 8, 14).date(),
            expected_net_alpha_pct=Decimal("2"),
            estimated_transaction_cost_eur=Decimal("0"),
            estimated_tax_impact_eur=Decimal("0"),
            risk_impact="Reduces concentration.",
            reference_price_eur=Decimal("10"),
            currency="EUR",
            execution_assumption="cash",
        )
