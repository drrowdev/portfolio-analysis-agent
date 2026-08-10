from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pandas as pd
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Base
from app.models.analysis import (
    AnalysisRun,
    RecommendationOutcome,
    ShadowRecommendation,
)
from app.models.transaction import TransactionType
from app.routers.holdings import _fifo_replay
from app.schemas.analysis import (
    AnalysisMetrics,
    AnalysisRecommendation,
    AnalysisResult,
    AnalysisRunMeta,
    AnalysisSource,
    AnalysisInsight,
    ProofOfValuePolicy,
    ModelAnalysisResult,
)
from app.services.analysis import _build_model_input, _validate_shadow_decisions
from app.services.alerts import generate_alerts_from_analysis
from app.schemas.portfolio import PerformanceDataPoint, PerformanceResponse
from app.services.analysis_metrics import (
    calculate_concentration,
    calculate_performance_risk,
    calculate_sector_exposure,
)
from app.services.analysis_outcomes import _evaluate_history
from app.services.analysis_baselines import evaluate_baselines
from app.services.analysis_snapshot import (
    _coverage_gaps,
    _replay_open_tax_lots,
    build_open_tax_lots,
)
from app.services.analysis_ledger import (
    analysis_input_hash,
    proof_of_value_report,
    record_completed_run,
)
from app.services.proof_of_value import REQUIRED_FIELDS, _policy_state
from app.services.analysis_safety import (
    contains_actionable_trade_instruction,
    numeric_grounding_claims,
)
from app.db_migrations import (
    LEGACY_SCHEMA_SENTINELS,
    MIGRATION_LOCK_ID,
    _postgres_migration_lock,
    classify_schema,
)


def test_policy_is_incomplete_until_risk_and_cost_limits_are_explicit():
    state = _policy_state(ProofOfValuePolicy())

    assert not state.is_complete
    assert state.mode == "shadow"
    assert state.missing_fields == list(REQUIRED_FIELDS)


def test_complete_model_input_hash_includes_news_and_request_configuration():
    first = _build_model_input("UNTRUSTED EXTERNAL NEWS:\nFirst article")
    second = _build_model_input("UNTRUSTED EXTERNAL NEWS:\nSecond article")

    assert first["request"]["system"]
    assert first["request"]["model"] == "claude-sonnet-5"
    assert first["request"]["thinking"] == {"type": "adaptive"}
    assert analysis_input_hash(first) != analysis_input_hash(second)


def test_migration_bootstrap_only_adopts_a_complete_legacy_schema():
    assert classify_schema(set()) == "empty"
    assert classify_schema({"alembic_version"}) == "versioned"
    assert classify_schema(set(LEGACY_SCHEMA_SENTINELS)) == "legacy_complete"
    with pytest.raises(RuntimeError, match="partial unversioned"):
        classify_schema({"accounts", "holdings"})
    with pytest.raises(RuntimeError, match="alerts"):
        classify_schema(set(LEGACY_SCHEMA_SENTINELS) - {"alerts"})


@pytest.mark.asyncio
async def test_postgres_migration_lock_is_released_after_failure():
    class RecordingConnection:
        def __init__(self):
            self.calls = []

        async def execute(self, statement, parameters):
            self.calls.append((str(statement), parameters))

    connection = RecordingConnection()

    with pytest.raises(RuntimeError, match="migration failed"):
        async with _postgres_migration_lock(connection):
            raise RuntimeError("migration failed")

    assert connection.calls == [
        (
            "SELECT pg_advisory_lock(:lock_id)",
            {"lock_id": MIGRATION_LOCK_ID},
        ),
        (
            "SELECT pg_advisory_unlock(:lock_id)",
            {"lock_id": MIGRATION_LOCK_ID},
        ),
    ]


def test_fidelity_coverage_detects_internal_statement_gap():
    gaps = _coverage_gaps(
        [
            (date(2026, 1, 1), date(2026, 1, 31)),
            (date(2026, 8, 1), date(2026, 8, 31)),
        ],
        date(2026, 1, 1),
        date(2026, 8, 31),
    )

    assert gaps == [(date(2026, 2, 1), date(2026, 7, 31))]


def test_fidelity_coverage_merges_overlapping_and_adjacent_statements():
    gaps = _coverage_gaps(
        [
            (date(2025, 12, 15), date(2026, 1, 31)),
            (date(2026, 1, 20), date(2026, 2, 15)),
            (date(2026, 2, 16), date(2026, 3, 31)),
        ],
        date(2026, 1, 1),
        date(2026, 3, 31),
    )

    assert gaps == []


def test_holding_fifo_includes_buy_fee_once_in_eur_and_native_basis():
    transaction = SimpleNamespace(
        transaction_type=TransactionType.buy,
        quantity=Decimal("1"),
        price_eur=Decimal("100"),
        total_eur=Decimal("100"),
        price_native=None,
        currency="EUR",
        fees=Decimal("10"),
        fx_rate=None,
    )

    quantity, cost_eur, cost_native, _ = _fifo_replay(
        [transaction],
        [TransactionType.buy],
        [TransactionType.sell],
    )

    assert quantity == Decimal("1")
    assert cost_eur == Decimal("110")
    assert cost_native == Decimal("110")


def test_complete_policy_has_no_implicit_assumptions():
    state = _policy_state(
        ProofOfValuePolicy(
            investment_horizon_years=5,
            max_drawdown_pct=25,
            max_annualized_volatility_pct=20,
            max_tracking_error_pct=10,
            max_single_position_pct=20,
            max_sector_pct=40,
            max_annual_turnover_pct=50,
            estimated_transaction_cost_bps=20,
            minimum_expected_net_alpha_pct=2,
        )
    )

    assert state.is_complete
    assert state.missing_fields == []
    assert "after-tax, after-cost" in state.objective


def test_performance_metrics_use_daily_returns_and_report_drawdown():
    response = PerformanceResponse(
        period="1y",
        start_date=date(2026, 1, 1),
        data=[
            PerformanceDataPoint(
                date=date(2026, 1, 1),
                portfolio_return_pct=0,
                sp500_return_pct=0,
                portfolio_value_eur=100,
            ),
            PerformanceDataPoint(
                date=date(2026, 1, 2),
                portfolio_return_pct=10,
                sp500_return_pct=5,
                portfolio_value_eur=110,
            ),
            PerformanceDataPoint(
                date=date(2026, 1, 3),
                portfolio_return_pct=-1,
                sp500_return_pct=4,
                portfolio_value_eur=99,
            ),
            PerformanceDataPoint(
                date=date(2026, 1, 4),
                portfolio_return_pct=8,
                sp500_return_pct=6,
                portfolio_value_eur=108,
            ),
        ],
    )

    metrics = calculate_performance_risk(response)

    assert metrics.portfolio_return_pct == 8
    assert metrics.benchmark_return_pct == 6
    assert metrics.active_return_pct == 2
    assert metrics.max_drawdown_pct == 10
    assert metrics.annualized_volatility_pct is not None
    assert metrics.tracking_error_pct is not None


def test_concentration_and_sector_metrics_are_value_weighted():
    concentration = calculate_concentration(
        [
            ("AAA", Decimal("600")),
            ("BBB", Decimal("300")),
            ("CCC", Decimal("100")),
        ]
    )
    sectors = calculate_sector_exposure(
        {"Technology": Decimal("900"), "Healthcare": Decimal("100")}
    )

    assert concentration.largest_position_symbol == "AAA"
    assert concentration.largest_position_pct == Decimal("60.00")
    assert concentration.herfindahl_index == Decimal("0.4600")
    assert sectors[0].sector == "Technology"
    assert sectors[0].weight_pct == Decimal("90.00")


def test_sector_exposure_keeps_unknown_positions_in_portfolio_denominator():
    sectors = calculate_sector_exposure(
        {"Technology": Decimal("200"), "Unknown": Decimal("600")},
        Decimal("1000"),
    )

    assert sectors[0].sector == "Unknown"
    assert sectors[0].weight_pct == Decimal("60.00")
    assert sectors[1].weight_pct == Decimal("20.00")


def test_open_tax_lots_replay_sells_fifo_per_account():
    transactions = [
        SimpleNamespace(
            account_id="account-a",
            symbol="MSFT",
            transaction_type=TransactionType.buy,
            quantity=Decimal("10"),
            price_eur=Decimal("100"),
            date=date(2024, 1, 1),
        ),
        SimpleNamespace(
            account_id="account-a",
            symbol="MSFT",
            transaction_type=TransactionType.buy,
            quantity=Decimal("5"),
            price_eur=Decimal("120"),
            date=date(2025, 1, 1),
        ),
        SimpleNamespace(
            account_id="account-a",
            symbol="MSFT",
            transaction_type=TransactionType.sell,
            quantity=Decimal("12"),
            price_eur=Decimal("150"),
            date=date(2026, 1, 1),
        ),
        SimpleNamespace(
            account_id="account-b",
            symbol="MSFT",
            transaction_type=TransactionType.buy,
            quantity=Decimal("3"),
            price_eur=Decimal("80"),
            date=date(2024, 1, 1),
        ),
    ]

    lots = build_open_tax_lots(transactions)

    assert [(lot.account_id, lot.quantity, lot.cost_per_share_eur) for lot in lots] == [
        ("account-a", Decimal("3"), Decimal("120")),
        ("account-b", Decimal("3"), Decimal("80")),
    ]


def test_tax_lot_replay_reports_sells_exceeding_recorded_lots():
    transactions = [
        SimpleNamespace(
            account_id="account-a",
            symbol="MSFT",
            transaction_type=TransactionType.buy,
            quantity=Decimal("1"),
            price_eur=Decimal("100"),
            date=date(2024, 1, 1),
        ),
        SimpleNamespace(
            account_id="account-a",
            symbol="MSFT",
            transaction_type=TransactionType.sell,
            quantity=Decimal("2"),
            price_eur=Decimal("150"),
            date=date(2026, 1, 1),
        ),
    ]

    _, unmatched = _replay_open_tax_lots(transactions)

    assert unmatched == {("account-a", "MSFT"): Decimal("1")}


def test_trade_recommendation_requires_deterministic_fields():
    with pytest.raises(ValidationError, match="deterministic fields"):
        AnalysisRecommendation(
            action="Buy MSFT",
            rationale="Narrative conviction is not enough.",
            account_type="AOT",
            priority="high",
            decision="buy",
            confidence="high",
            urgency="immediate",
            symbol="MSFT",
        )


def test_non_trade_decision_rejects_executable_fields():
    with pytest.raises(ValidationError, match="Non-trade decisions"):
        AnalysisRecommendation(
            action="Hold",
            rationale="No deterministic candidate.",
            priority="medium",
            decision="hold",
            confidence="high",
            urgency="routine",
            amount_eur=Decimal("1000"),
        )


def test_trade_decision_requires_explicit_tax_impact():
    with pytest.raises(ValidationError, match="estimated_tax_impact_eur"):
        AnalysisRecommendation(
            action="Sell MSFT",
            rationale="Deterministic candidate.",
            priority="medium",
            decision="sell",
            confidence="high",
            urgency="routine",
            symbol="MSFT",
            amount_eur=Decimal("1000"),
            expected_net_alpha_pct=Decimal("2"),
            downside_pct=Decimal("5"),
            estimated_transaction_cost_eur=Decimal("2"),
            risk_impact="Reduces concentration.",
            reference_price_eur=Decimal("400"),
            currency="USD",
            execution_assumption="benchmark",
        )


def test_non_trade_shadow_decision_does_not_invent_trade_math():
    recommendation = AnalysisRecommendation(
        action="Monitor MSFT concentration",
        rationale="A deterministic candidate has not been generated.",
        priority="medium",
        decision="monitor",
        confidence="high",
        urgency="routine",
        symbol="MSFT",
    )

    assert recommendation.amount_eur is None
    assert recommendation.expected_net_alpha_pct is None


def test_outcomes_measure_value_add_and_benchmark_alpha_after_drag():
    dates = pd.bdate_range("2026-01-02", periods=62)
    outcomes = _evaluate_history(
        created_at=datetime(2026, 1, 1),
        decision="buy",
        execution_assumption="cash",
        amount_eur=100,
        transaction_cost_eur=1,
        tax_impact_eur=0.5,
        asset_eur=pd.Series(range(100, 162), index=dates, dtype=float),
        benchmark_eur=pd.Series(
            [100 + index * 0.5 for index in range(62)],
            index=dates,
            dtype=float,
        ),
    )

    assert [outcome["horizon_days"] for outcome in outcomes] == [1, 5, 20, 60]
    assert outcomes[0]["gross_value_add_pct"] == pytest.approx(1)
    assert outcomes[0]["net_value_add_pct"] == pytest.approx(-0.5)
    assert outcomes[0]["net_active_return_pct"] == pytest.approx(-1)
    assert outcomes[-1]["net_value_add_pct"] == pytest.approx(58.5)
    assert outcomes[-1]["net_active_return_pct"] == pytest.approx(28.5)


def test_outcome_horizons_count_only_common_market_closes():
    dates = pd.bdate_range("2026-01-02", periods=62)
    asset_dates = dates.delete([10, 20])
    outcomes = _evaluate_history(
        created_at=datetime(2026, 1, 1),
        decision="buy",
        execution_assumption="cash",
        amount_eur=100,
        transaction_cost_eur=0,
        tax_impact_eur=0,
        asset_eur=pd.Series(range(100, 160), index=asset_dates, dtype=float),
        benchmark_eur=pd.Series(100, index=dates, dtype=float),
    )

    assert [outcome["horizon_days"] for outcome in outcomes] == [1, 5, 20]


def test_chat_guard_blocks_direct_trade_instructions():
    assert contains_actionable_trade_instruction("You should sell MSFT immediately.")
    assert contains_actionable_trade_instruction(
        "Based on these risks, you should sell MSFT immediately."
    )
    assert contains_actionable_trade_instruction(
        "My recommendation is to rebalance into bonds."
    )
    assert contains_actionable_trade_instruction(
        "I recommend selling 10 shares."
    )
    assert contains_actionable_trade_instruction(
        "MSFT should be sold immediately."
    )
    assert not contains_actionable_trade_instruction(
        "You should not sell without validated evidence."
    )
    assert not contains_actionable_trade_instruction(
        "Selling a position may create a taxable event."
    )


def test_structured_analysis_rejects_trade_instruction_hidden_in_rationale():
    result = ModelAnalysisResult(
        summary="Monitor the evidence.",
        recommendations=[
            AnalysisRecommendation(
                action="Monitor MSFT",
                rationale="Based on these risks, you should sell MSFT immediately.",
                priority="high",
                decision="monitor",
                confidence="medium",
                urgency="soon",
                symbol="MSFT",
            )
        ],
    )

    with pytest.raises(ValueError, match="actionable trade instruction"):
        _validate_shadow_decisions(result)


def test_shared_output_guard_rejects_numbers_absent_from_grounding():
    result = ModelAnalysisResult(
        summary="MSFT has a €550 target price, 18% expected alpha, and 7% downside."
    )
    allowed = numeric_grounding_claims(
        structured={
            "current_price_eur": "421.25",
            "max_drawdown_pct": "25",
        }
    )

    with pytest.raises(ValueError, match="numerical claims"):
        _validate_shadow_decisions(
            result,
            allowed_numeric_claims=allowed,
        )


def test_shared_output_guard_accepts_exact_grounded_numbers():
    result = ModelAnalysisResult(
        summary="The supplied current price is €421.25 and the drawdown limit is 25%."
    )
    allowed = numeric_grounding_claims(
        structured={
            "current_price_eur": "421.25",
            "max_drawdown_pct": "25",
        }
    )

    _validate_shadow_decisions(
        result,
        allowed_numeric_claims=allowed,
    )


def test_structured_analysis_rejects_unsupplied_citation_url():
    result = ModelAnalysisResult(
        summary="Material news requires monitoring.",
        insights=[
            AnalysisInsight(
                title="Earnings update",
                detail="Reported revenue changed.",
                severity="info",
                sources=[
                    AnalysisSource(
                        name="Invented",
                        url="https://example.invalid/invented",
                        date="1.1.2026",
                    )
                ],
            )
        ],
    )

    with pytest.raises(ValueError, match="citation URL"):
        _validate_shadow_decisions(result, {"https://trusted.example/article"})


def test_rules_baseline_flags_explicit_risk_breaches():
    policy = _policy_state(
        ProofOfValuePolicy(
            investment_horizon_years=5,
            max_drawdown_pct=8,
            max_annualized_volatility_pct=100,
            max_tracking_error_pct=100,
            max_single_position_pct=50,
            max_sector_pct=80,
            max_annual_turnover_pct=50,
            estimated_transaction_cost_bps=20,
            minimum_expected_net_alpha_pct=2,
        )
    )
    performance = calculate_performance_risk(
        PerformanceResponse(
            period="1y",
            start_date=date(2026, 1, 1),
            data=[
                PerformanceDataPoint(
                    date=date(2026, 1, 1),
                    portfolio_return_pct=0,
                    sp500_return_pct=0,
                    portfolio_value_eur=100,
                ),
                PerformanceDataPoint(
                    date=date(2026, 1, 2),
                    portfolio_return_pct=10,
                    sp500_return_pct=5,
                    portfolio_value_eur=110,
                ),
                PerformanceDataPoint(
                    date=date(2026, 1, 3),
                    portfolio_return_pct=-1,
                    sp500_return_pct=4,
                    portfolio_value_eur=99,
                ),
            ],
        )
    )
    metrics = AnalysisMetrics(
        performance=performance,
        concentration=calculate_concentration(
            [("AAA", Decimal("600")), ("BBB", Decimal("400"))]
        ),
        sectors=calculate_sector_exposure(
            {"Technology": Decimal("900"), "Healthcare": Decimal("100")}
        ),
    )

    baseline = evaluate_baselines(policy, metrics)

    assert baseline.deterministic_policy_status == "blocked"
    breached = {
        signal.code for signal in baseline.signals if signal.status == "breach"
    }
    assert {
        "single_position_limit",
        "sector_limit",
        "drawdown_limit",
    }.issubset(breached)


@pytest.mark.asyncio
async def test_shadow_analysis_never_creates_alerts():
    await generate_alerts_from_analysis(
        object(),
        {
            "meta": {"mode": "shadow"},
            "recommendations": [
                {
                    "priority": "high",
                    "action": "This must not become an alert",
                }
            ],
        },
    )


@pytest.mark.asyncio
async def test_completed_run_persists_validated_shadow_recommendations():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    policy = _policy_state(ProofOfValuePolicy())
    result = AnalysisResult(
        summary="No trade",
        recommendations=[
            AnalysisRecommendation(
                action="Wait for complete inputs",
                rationale="The risk contract is incomplete.",
                priority="high",
                decision="abstain",
                confidence="high",
                urgency="none",
            )
        ],
        meta=AnalysisRunMeta(
            as_of=datetime.now(timezone.utc),
            snapshot_hash=None,
            model="claude-sonnet-5",
            prompt_version="proof-of-value-v1",
            can_recommend_trades=False,
            data_quality_issues=["policy_incomplete"],
        ),
    )

    async with session_factory() as session:
        await record_completed_run(
            session,
            analysis_type="rebalance",
            policy=policy,
            result=result,
            snapshot=None,
        )
        await session.commit()

    async with session_factory() as session:
        run = (await session.execute(select(AnalysisRun))).scalar_one()
        recommendation = (
            await session.execute(select(ShadowRecommendation))
        ).scalar_one()
        assert run.mode == "shadow"
        assert run.status == "completed"
        assert recommendation.run_id == run.id
        assert recommendation.decision == "abstain"
        report = await proof_of_value_report(session)
        assert report.total_runs == 1
        assert report.reproducible_runs == 0
        assert report.decision_counts == {"abstain": 1}
        assert report.investment_evidence == "insufficient"

    await engine.dispose()


@pytest.mark.asyncio
async def test_completed_run_persists_and_counts_complete_input_record():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    input_json = _build_model_input(
        "UNTRUSTED EXTERNAL NEWS:\n- [MSFT] Material public article"
    )
    input_hash = analysis_input_hash(input_json)
    result = AnalysisResult(
        summary="Monitor public information without trading.",
        meta=AnalysisRunMeta(
            as_of=datetime.now(timezone.utc),
            snapshot_hash=None,
            input_hash=input_hash,
            model="claude-sonnet-5",
            prompt_version="proof-of-value-v1",
            can_recommend_trades=False,
        ),
    )

    async with session_factory() as session:
        await record_completed_run(
            session,
            analysis_type="news_impact",
            policy=_policy_state(ProofOfValuePolicy()),
            result=result,
            snapshot=None,
            input_json=input_json,
        )
        await session.commit()

    async with session_factory() as session:
        run = (await session.execute(select(AnalysisRun))).scalar_one()
        assert run.input_hash == input_hash
        assert run.input_json == input_json
        assert (await proof_of_value_report(session)).reproducible_runs == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_risk_enforcement_outcomes_do_not_count_as_alpha_evidence():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        run = AnalysisRun(
            analysis_type="rebalance",
            mode="shadow",
            status="completed",
            model_name="claude-sonnet-5",
            prompt_version="proof-of-value-v1",
            policy_json={},
            data_quality_json={},
        )
        session.add(run)
        await session.flush()
        recommendation = ShadowRecommendation(
            run_id=run.id,
            decision="sell",
            symbol="MSFT",
            status="evaluated",
            recommendation_json={
                "candidate_objective": "risk_enforcement",
                "account_id": "aot",
                "execution_assumption": "cash",
            },
        )
        session.add(recommendation)
        await session.flush()
        session.add(
            RecommendationOutcome(
                recommendation_id=recommendation.id,
                horizon_trading_days=20,
                evaluated_at=datetime.now(timezone.utc).replace(tzinfo=None),
                outcome_json={
                    "fill_date": "2026-01-02",
                    "net_value_add_pct": 3,
                    "net_active_return_pct": 2,
                    "met_expected_alpha": None,
                },
            )
        )
        await session.commit()

    async with session_factory() as session:
        report = await proof_of_value_report(session)
        assert report.evaluated_recommendations == 1
        assert report.horizon_evidence[0].horizon_trading_days == 20
        assert (
            report.horizon_evidence[0].candidate_objective
            == "risk_enforcement"
        )
        assert report.investment_evidence == "insufficient"
        assert "Risk-enforcement outcomes" in report.evidence_message

    await engine.dispose()
