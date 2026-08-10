from copy import deepcopy
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.models import Base
from app.models.backtest import BacktestRun
from app.services.backtest_engine import (
    _AlignedPrices,
    _TradeEvent,
    _signal_snapshot,
    _split_metrics,
    run_point_in_time_universe_backtest,
)
from app.services.backtest_market_data import (
    _extract_adjusted_close,
    _extract_stock_splits,
)
from app.services.backtest_personal import (
    audit_personal_ledger,
    run_personal_transaction_backtest,
)
from app.services.backtest_spec import (
    LockedBacktestInputs,
    MembershipInterval,
    load_locked_backtest_inputs,
    members_on,
)
from app.services.backtests import run_backtest
from app.models.transaction import TransactionType
from app.routers.upload import (
    _fidelity_transaction_key,
    _is_nordnet_lot_import,
)


def _locked(
    *,
    intervals: tuple[MembershipInterval, ...],
) -> LockedBacktestInputs:
    original = load_locked_backtest_inputs()
    specification = deepcopy(original.specification)
    specification["signal"].update(
        {
            "momentum_lookback_trading_days": 5,
            "momentum_skip_recent_trading_days": 1,
            "trend_sma_trading_days": 3,
        }
    )
    specification["periods"] = {
        "warmup": {"start": "2019-01-01", "end": "2019-12-31"},
        "development": {"start": "2020-01-01", "end": "2020-04-30"},
        "validation": {"start": "2020-05-01", "end": "2020-08-31"},
        "holdout": {
            "start": "2020-09-01",
            "end": "2020-12-31",
            "sealed_before_first_run": True,
        },
    }
    specification["statistics"].update(
        {
            "bootstrap_samples": 100,
            "bootstrap_block_months": 2,
            "minimum_holdout_months": 1,
        }
    )
    specification["universe_track"].update(
        {
            "maximum_selected_names": 1,
            "active_sleeve_pct": 20.0,
            "benchmark_core_pct": 80.0,
        }
    )
    return LockedBacktestInputs(
        specification=specification,
        specification_hash="a" * 64,
        membership_provenance={"source_commit": "test-commit"},
        membership_hash="b" * 64,
        membership_intervals=intervals,
    )


def _policy() -> SimpleNamespace:
    return SimpleNamespace(
        estimated_transaction_cost_bps=10,
        minimum_expected_net_alpha_pct=0,
        max_drawdown_pct=50,
        max_annualized_volatility_pct=100,
        max_tracking_error_pct=100,
        max_annual_turnover_pct=10_000,
        max_single_position_pct=10,
    )


def _rising_prices() -> pd.DataFrame:
    dates = pd.bdate_range("2019-01-01", "2020-12-31")
    steps = pd.Series(range(len(dates)), index=dates, dtype=float)
    return pd.DataFrame(
        {
            "^SP500TR": 100 * (1.0002 ** steps),
            "AAA": 100 * (1.001 ** steps),
        },
        index=dates,
    )


def _no_splits(prices: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({"AAA": 0.0}, index=prices.index)


def test_locked_inputs_are_hashed_and_membership_is_point_in_time():
    locked = load_locked_backtest_inputs()

    assert len(locked.specification_hash) == 64
    assert len(locked.membership_hash) == 64
    assert len(locked.membership_intervals) == 1259
    assert "AAPL" in members_on(locked.membership_intervals, date(2005, 1, 3))
    assert "ENRNQ" not in members_on(
        locked.membership_intervals,
        date(2005, 1, 3),
    )


def test_signal_does_not_read_prices_after_the_signal_close():
    prices = _rising_prices()
    locked = _locked(
        intervals=(MembershipInterval("AAA", date(2019, 1, 1), None),)
    )
    signal_at = pd.Timestamp("2020-06-30")
    aligned = _AlignedPrices(prices, "^SP500TR", 4)
    before = _signal_snapshot(
        aligned,
        signal_at=signal_at,
        candidates={"AAA"},
        benchmark="^SP500TR",
        specification=locked.specification,
    )

    changed = prices.copy()
    changed.loc[changed.index > signal_at, "AAA"] *= 100
    after = _signal_snapshot(
        _AlignedPrices(changed, "^SP500TR", 4),
        signal_at=signal_at,
        candidates={"AAA"},
        benchmark="^SP500TR",
        specification=locked.specification,
    )

    assert before == after
    assert "AAA" in before


def test_personal_market_snapshot_extracts_split_events_by_original_symbol():
    dates = pd.to_datetime(["2020-01-02", "2020-06-01"])
    raw = pd.DataFrame(
        {
            ("Stock Splits", "AAA.Y"): [0.0, 2.0],
            ("Stock Splits", "^SP500TR"): [0.0, 0.0],
        },
        index=dates,
    )

    splits = _extract_stock_splits(raw, {"AAA": "AAA.Y"})

    assert list(splits.columns) == ["AAA"]
    assert splits.loc[pd.Timestamp("2020-06-01"), "AAA"] == 2


def test_personal_market_snapshot_rejects_raw_close_fallback():
    raw = pd.DataFrame(
        {"Close": [100.0]},
        index=pd.to_datetime(["2020-01-02"]),
    )

    assert _extract_adjusted_close(raw, "AAA").empty


def test_universe_track_fails_closed_when_a_historical_member_has_no_prices():
    locked = _locked(
        intervals=(
            MembershipInterval("AAA", date(2019, 1, 1), None),
            MembershipInterval("DELISTED", date(2020, 1, 1), date(2020, 6, 30)),
        )
    )

    result = run_point_in_time_universe_backtest(
        prices_eur=_rising_prices(),
        price_data_hash="c" * 64,
        price_data_source="test",
        locked=locked,
        policy=_policy(),
    )

    assert result["status"] == "blocked"
    assert result["data_manifest"]["missing_members"] == ["DELISTED"]
    assert "delisted-security source is required" in result["blockers"][0]


def test_universe_track_fails_closed_on_partial_delisted_price_history():
    locked = _locked(
        intervals=(
            MembershipInterval("AAA", date(2019, 1, 1), None),
            MembershipInterval("DELISTED", date(2020, 1, 1), date(2020, 6, 30)),
        )
    )
    prices = _rising_prices()
    prices["DELISTED"] = float("nan")
    prices.loc[pd.Timestamp("2020-01-02"), "DELISTED"] = 10

    result = run_point_in_time_universe_backtest(
        prices_eur=prices,
        price_data_hash="c" * 64,
        price_data_source="test",
        locked=locked,
        policy=_policy(),
    )

    assert result["status"] == "blocked"
    failure = result["data_manifest"]["coverage_failures"][0]
    assert failure["ticker"] == "DELISTED"
    assert failure["coverage_pct"] < 100


def test_universe_track_fails_closed_on_truncated_registered_periods():
    locked = _locked(
        intervals=(MembershipInterval("AAA", date(2019, 1, 1), None),)
    )
    prices = _rising_prices().loc["2020-05-01":"2020-12-31"]

    result = run_point_in_time_universe_backtest(
        prices_eur=prices,
        price_data_hash="c" * 64,
        price_data_source="test",
        locked=locked,
        policy=_policy(),
    )

    assert result["status"] == "blocked"
    failed_periods = {
        failure["period"]
        for failure in result["data_manifest"]["period_coverage_failures"]
    }
    assert {"warmup", "development"} <= failed_periods


def test_universe_track_fails_closed_on_sparse_benchmark_sessions():
    locked = _locked(
        intervals=(MembershipInterval("AAA", date(2019, 1, 1), None),)
    )
    prices = _rising_prices().iloc[::2]

    result = run_point_in_time_universe_backtest(
        prices_eur=prices,
        price_data_hash="c" * 64,
        price_data_source="test",
        locked=locked,
        policy=_policy(),
    )

    assert result["status"] == "blocked"
    failures = result["data_manifest"]["period_coverage_failures"]
    assert sum(failure["missing_session_count"] for failure in failures) > 0


def test_universe_track_runs_both_tax_scenarios_without_parameter_search():
    locked = _locked(
        intervals=(MembershipInterval("AAA", date(2019, 1, 1), None),)
    )

    result = run_point_in_time_universe_backtest(
        prices_eur=_rising_prices(),
        price_data_hash="c" * 64,
        price_data_source="test",
        locked=locked,
        policy=_policy(),
    )

    assert result["status"] == "completed_with_exclusions"
    assert set(result["scenarios"]) == {"deferred", "standard"}
    holdout = next(
        split
        for split in result["scenarios"]["deferred"]["splits"]
        if split["period"] == "holdout"
    )
    assert holdout["observations"] > 0
    assert holdout["net_active_cagr_pct"] > 0
    assert result["scenarios"]["standard"]["status"] == "blocked"
    assert "dividends" in result["scenarios"]["standard"]["blockers"][0]
    assert result["promotion_eligible"] is False
    assert any(
        "sector" in blocker.lower()
        for blocker in result["promotion_blockers"]
    )


def test_turnover_uses_portfolio_value_at_each_trade():
    dates = pd.bdate_range("2020-01-01", "2020-12-31")
    daily = pd.DataFrame(
        {
            "strategy_return": [0.0] * len(dates),
            "benchmark_return": [0.0] * len(dates),
            "portfolio_value": [200_000.0] * len(dates),
        },
        index=dates,
    )
    metrics = _split_metrics(
        daily,
        [
            _TradeEvent(
                event_date=date(2020, 6, 1),
                portfolio_value_eur=200_000,
                gross_notional_eur=20_000,
                transaction_cost_eur=0,
                tax_eur=0,
            )
        ],
        split_name="holdout",
        start=date(2020, 1, 1),
        end=date(2020, 12, 31),
        specification=_locked(intervals=()).specification,
    )

    assert 9.9 < metrics["annualized_gross_turnover_pct"] < 10.1


def test_import_note_does_not_override_reconciled_user_history():
    accounts = [
        {
            "id": "account-1",
            "name": "OST",
            "account_type": "osakesaastotili",
            "tax_treatment": "deferred",
        }
    ]
    holdings = [
        {
            "account_id": "account-1",
            "symbol": "AAA",
            "quantity": "2",
        }
    ]
    transactions = [
        {
            "id": "buy-1",
            "account_id": "account-1",
            "symbol": "AAA",
            "transaction_type": "buy",
            "date": date(2020, 1, 2),
            "quantity": "2",
            "notes": "Imported from Nordnet lot export (2026-08-05)",
        }
    ]

    coverage = audit_personal_ledger(
        accounts=accounts,
        holdings=holdings,
        transactions=transactions,
    )

    assert coverage["can_backtest_all_accounts"] is True
    assert coverage["accounts"][0]["eligible"] is True
    assert coverage["accounts"][0]["source_markers"] == [
        "nordnet_open_lot_export"
    ]


def test_open_lot_reimport_cannot_replace_full_or_manual_history():
    assert _is_nordnet_lot_import(
        SimpleNamespace(notes="Imported from Nordnet lot export (2026-08-05)")
    )
    assert not _is_nordnet_lot_import(
        SimpleNamespace(notes="Imported from Nordnet transaction history")
    )
    assert not _is_nordnet_lot_import(SimpleNamespace(notes=None))


def test_fidelity_overlap_identity_uses_native_values():
    first = _fidelity_transaction_key(
        symbol="MSFT",
        transaction_type=TransactionType.espp_purchase,
        transaction_date=date(2026, 3, 31),
        quantity=Decimal("1.2500"),
        price_native=Decimal("400.00"),
        total_native=Decimal("500.000"),
    )
    second = _fidelity_transaction_key(
        symbol="MSFT",
        transaction_type=TransactionType.espp_purchase,
        transaction_date=date(2026, 3, 31),
        quantity=Decimal("1.25"),
        price_native=Decimal("400"),
        total_native=Decimal("500"),
    )

    assert first == second


def test_personal_track_uses_only_pre_purchase_signal_and_fifo_cohorts():
    locked = _locked(
        intervals=(MembershipInterval("AAA", date(2019, 1, 1), None),)
    )
    dates = pd.bdate_range("2019-01-01", "2020-12-31")
    benchmark = pd.Series(
        [100 + index * 0.05 for index in range(len(dates))],
        index=dates,
    )
    asset = pd.Series(
        [200 - index * 0.1 for index in range(len(dates))],
        index=dates,
    )
    purchase_date = date(2020, 9, 15)
    asset.loc[asset.index >= pd.Timestamp(purchase_date)] = 250
    prices = pd.DataFrame({"^SP500TR": benchmark, "AAA": asset})
    accounts = [
        {
            "id": "account-1",
            "name": "Deferred",
            "account_type": "osakesaastotili",
            "tax_treatment": "deferred",
            "currency": "EUR",
        }
    ]
    holdings = [
        {
            "id": "holding-1",
            "account_id": "account-1",
            "symbol": "AAA",
            "quantity": "1",
            "currency": "EUR",
        }
    ]
    transactions = [
        {
            "id": "buy-1",
            "account_id": "account-1",
            "tax_treatment": "deferred",
            "symbol": "AAA",
            "currency": "EUR",
            "transaction_type": "buy",
            "date": purchase_date,
            "quantity": "1",
            "price_eur": "250",
            "total_eur": "250",
            "fees": "1",
            "notes": None,
        }
    ]

    result = run_personal_transaction_backtest(
        prices_eur=prices,
        split_events=_no_splits(prices),
        price_data_hash="c" * 64,
        price_data_source="test",
        locked=locked,
        policy=_policy(),
        accounts=accounts,
        holdings=holdings,
        transactions=transactions,
    )

    holdout = next(
        split for split in result["split_results"] if split["period"] == "holdout"
    )
    assert result["status"] == "completed"
    assert result["cohort_count"] == 1
    assert holdout["signal_pass_rate_pct"] == 0
    assert holdout["overlay_net_value_add_pct"] > 0
    assert result["promotion_eligible"] is False


def test_personal_track_fails_closed_when_prices_end_before_holdout():
    locked = _locked(
        intervals=(MembershipInterval("AAA", date(2019, 1, 1), None),)
    )
    prices = _rising_prices().loc[:"2020-10-30"]
    accounts = [
        {
            "id": "account-1",
            "name": "AOT",
            "account_type": "arvo_osuustili",
            "tax_treatment": "deferred",
        }
    ]
    holdings = [
        {"account_id": "account-1", "symbol": "AAA", "quantity": "1"}
    ]
    transactions = [
        {
            "id": "buy-1",
            "account_id": "account-1",
            "tax_treatment": "deferred",
            "symbol": "AAA",
            "currency": "EUR",
            "transaction_type": "buy",
            "date": date(2020, 9, 15),
            "quantity": "1",
            "price_eur": "100",
            "total_eur": "100",
            "fees": "0",
        }
    ]

    result = run_personal_transaction_backtest(
        prices_eur=prices,
        split_events=_no_splits(prices),
        price_data_hash="c" * 64,
        price_data_source="test",
        locked=locked,
        policy=_policy(),
        accounts=accounts,
        holdings=holdings,
        transactions=transactions,
    )

    assert result["status"] == "blocked"
    assert result["data_manifest"]["registered_end"] == "2020-12-31"
    assert "registered holdout end" in result["blockers"][0]


def test_personal_failed_signal_replaces_only_registered_active_sleeve():
    locked = _locked(
        intervals=(MembershipInterval("AAA", date(2019, 1, 1), None),)
    )
    dates = pd.bdate_range("2019-01-01", "2020-12-31")
    benchmark = pd.Series(
        [100 + index * 0.1 for index in range(len(dates))],
        index=dates,
    )
    asset = pd.Series(
        [300 - index * 0.1 for index in range(len(dates))],
        index=dates,
    )
    purchase_date = date(2020, 9, 15)
    asset.loc[asset.index >= pd.Timestamp(purchase_date)] = 250
    prices = pd.DataFrame({"^SP500TR": benchmark, "AAA": asset})
    accounts = [
        {
            "id": "account-1",
            "name": "Deferred",
            "account_type": "osakesaastotili",
            "tax_treatment": "deferred",
        }
    ]
    holdings = [
        {"account_id": "account-1", "symbol": "AAA", "quantity": "1"}
    ]
    transactions = [
        {
            "id": "buy-1",
            "account_id": "account-1",
            "tax_treatment": "deferred",
            "symbol": "AAA",
            "currency": "EUR",
            "transaction_type": "buy",
            "date": purchase_date,
            "quantity": "1",
            "price_eur": "250",
            "total_eur": "250",
            "fees": "0",
        }
    ]
    policy = _policy()
    policy.estimated_transaction_cost_bps = 0

    result = run_personal_transaction_backtest(
        prices_eur=prices,
        split_events=_no_splits(prices),
        price_data_hash="c" * 64,
        price_data_source="test",
        locked=locked,
        policy=policy,
        accounts=accounts,
        holdings=holdings,
        transactions=transactions,
    )

    holdout = next(
        split for split in result["split_results"] if split["period"] == "holdout"
    )
    benchmark_growth = (
        benchmark.loc["2020-12-31"]
        / benchmark.loc[pd.Timestamp(purchase_date)]
    )
    expected_overlay_return = (0.8 + 0.2 * benchmark_growth - 1) * 100
    assert holdout["signal_pass_rate_pct"] == 0
    assert holdout["baseline_net_return_pct"] == pytest.approx(0)
    assert holdout["overlay_net_return_pct"] == pytest.approx(
        expected_overlay_return
    )
    assert holdout["failing_cohort_asset_minus_benchmark_pct"] == pytest.approx(
        (1 - benchmark_growth) * 100
    )


def test_personal_track_normalizes_split_adjusted_fifo_quantities():
    locked = _locked(
        intervals=(MembershipInterval("AAA", date(2019, 1, 1), None),)
    )
    prices = _rising_prices()
    split_events = _no_splits(prices)
    split_events.loc[pd.Timestamp("2020-06-01"), "AAA"] = 2
    accounts = [
        {
            "id": "account-1",
            "name": "Deferred",
            "account_type": "osakesaastotili",
            "tax_treatment": "deferred",
        }
    ]
    holdings = [
        {"account_id": "account-1", "symbol": "AAA", "quantity": "1"}
    ]
    transactions = [
        {
            "id": "buy-1",
            "account_id": "account-1",
            "tax_treatment": "deferred",
            "symbol": "AAA",
            "currency": "EUR",
            "transaction_type": "buy",
            "date": date(2020, 1, 15),
            "quantity": "1",
            "price_eur": "100",
            "total_eur": "100",
            "fees": "0",
        },
        {
            "id": "sell-1",
            "account_id": "account-1",
            "tax_treatment": "deferred",
            "symbol": "AAA",
            "currency": "EUR",
            "transaction_type": "sell",
            "date": date(2020, 7, 1),
            "quantity": "1",
            "price_eur": "60",
            "total_eur": "60",
            "fees": "0",
        },
    ]

    result = run_personal_transaction_backtest(
        prices_eur=prices,
        split_events=split_events,
        price_data_hash="c" * 64,
        price_data_source="test",
        locked=locked,
        policy=_policy(),
        accounts=accounts,
        holdings=holdings,
        transactions=transactions,
    )

    development = next(
        split
        for split in result["split_results"]
        if split["period"] == "development"
    )
    assert result["status"] == "completed"
    assert result["cohort_count"] == 2
    assert result["coverage"]["accounts"][0]["eligible"] is True
    assert development["entry_notional_eur"] == pytest.approx(100)


def test_personal_standard_account_blocks_without_dividend_tax_inputs():
    locked = _locked(
        intervals=(MembershipInterval("AAA", date(2019, 1, 1), None),)
    )
    dates = pd.bdate_range("2019-01-01", "2020-12-31")
    purchase_at = dates.get_loc(pd.Timestamp("2020-09-15"))
    remaining = len(dates) - purchase_at
    benchmark = pd.Series(100.0, index=dates)
    benchmark.iloc[purchase_at:] = [
        100 + 200 * index / (remaining - 1)
        for index in range(remaining)
    ]
    asset = pd.Series(
        [
            200 - 100 * index / purchase_at
            if index <= purchase_at
            else 100 + 100 * (index - purchase_at) / (remaining - 1)
            for index in range(len(dates))
        ],
        index=dates,
    )
    prices = pd.DataFrame({"^SP500TR": benchmark, "AAA": asset})
    accounts = [
        {
            "id": "account-1",
            "name": "AOT",
            "account_type": "arvo_osuustili",
            "tax_treatment": "standard",
        }
    ]
    holdings = [
        {"account_id": "account-1", "symbol": "AAA", "quantity": "1"}
    ]
    transactions = [
        {
            "id": "buy-1",
            "account_id": "account-1",
            "tax_treatment": "standard",
            "symbol": "AAA",
            "currency": "EUR",
            "transaction_type": "buy",
            "date": date(2020, 9, 15),
            "quantity": "1",
            "price_eur": "100000",
            "total_eur": "100000",
            "fees": "0",
        }
    ]
    policy = _policy()
    policy.estimated_transaction_cost_bps = 0

    result = run_personal_transaction_backtest(
        prices_eur=prices,
        split_events=_no_splits(prices),
        price_data_hash="c" * 64,
        price_data_source="test",
        locked=locked,
        policy=policy,
        accounts=accounts,
        holdings=holdings,
        transactions=transactions,
    )

    assert result["status"] == "blocked"
    assert "dividends" in result["blockers"][0]


def test_personal_passing_signal_reports_asset_minus_benchmark():
    locked = _locked(
        intervals=(MembershipInterval("AAA", date(2019, 1, 1), None),)
    )
    prices = _rising_prices()
    purchase_date = date(2020, 9, 15)
    entry_price = prices.loc[pd.Timestamp(purchase_date), "AAA"]
    accounts = [
        {
            "id": "account-1",
            "name": "Deferred",
            "account_type": "osakesaastotili",
            "tax_treatment": "deferred",
        }
    ]
    holdings = [
        {"account_id": "account-1", "symbol": "AAA", "quantity": "1"}
    ]
    transactions = [
        {
            "id": "buy-1",
            "account_id": "account-1",
            "tax_treatment": "deferred",
            "symbol": "AAA",
            "currency": "EUR",
            "transaction_type": "buy",
            "date": purchase_date,
            "quantity": "1",
            "price_eur": str(entry_price),
            "total_eur": str(entry_price),
            "fees": "0",
        }
    ]

    result = run_personal_transaction_backtest(
        prices_eur=prices,
        split_events=_no_splits(prices),
        price_data_hash="c" * 64,
        price_data_source="test",
        locked=locked,
        policy=_policy(),
        accounts=accounts,
        holdings=holdings,
        transactions=transactions,
    )

    holdout = next(
        split for split in result["split_results"] if split["period"] == "holdout"
    )
    assert holdout["signal_pass_rate_pct"] == 100
    assert holdout["passing_cohort_asset_minus_benchmark_pct"] > 0
    assert holdout["overlay_net_value_add_pct"] == pytest.approx(0)


@pytest.mark.asyncio
async def test_blocked_backtest_attempts_are_persisted_immutably(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(settings, "BACKTEST_MARKET_DATA_PATH", "")

    async with session_factory() as db:
        personal = await run_backtest(db, "actual_portfolio")
        universe = await run_backtest(db, "sp500_universe")
        await db.commit()
        rows = list(
            (
                await db.execute(
                    select(BacktestRun).order_by(BacktestRun.track)
                )
            ).scalars().all()
        )

    assert personal["status"] == "blocked"
    assert universe["status"] == "blocked"
    assert len(rows) == 2
    assert all(len(row.input_hash) == 64 for row in rows)
    assert all(row.result_json["run_id"] == str(row.id) for row in rows)
    await engine.dispose()
