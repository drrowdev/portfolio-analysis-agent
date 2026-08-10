"""Regression tests for the portfolio vs S&P 500 performance comparison."""

import asyncio
from datetime import date, datetime, timedelta
from decimal import Decimal

import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Base
from app.models.account import Account, AccountType, TaxTreatment
from app.models.cache import CacheEntry
from app.models.holding import Holding
from app.models.transaction import Transaction, TransactionType
from app.routers import upload as upload_router
from app.services import portfolio
from app.services.csv_parser import (
    FidelityHolding,
    FidelityParseResult,
    FidelityTransaction,
)


def _market_frame(
    dates: list[date],
    series: dict[str, list[float | None]],
    adjusted_series: dict[str, list[float | None]] | None = None,
) -> pd.DataFrame:
    data: dict[tuple[str, str], list[float | None]] = {
        ("Close", ticker): values
        for ticker, values in series.items()
    }
    data.update({
        ("Adj Close", ticker): values
        for ticker, values in (adjusted_series or series).items()
    })
    for ticker in series:
        if ticker != portfolio.BENCHMARK_TICKER and not ticker.endswith("=X"):
            data[("Stock Splits", ticker)] = [0] * len(dates)
    return pd.DataFrame(data, index=pd.to_datetime(dates)).sort_index(axis=1)


def _transaction(
    symbol: str,
    transaction_date: date,
    quantity: float,
    transaction_type: str = "buy",
    currency: str = "EUR",
    account_id: str = "",
    notes: str = "",
) -> dict:
    return {
        "account_id": account_id,
        "symbol": symbol,
        "date": transaction_date,
        "quantity": quantity,
        "total_eur": 0,
        "transaction_type": transaction_type,
        "currency": currency,
        "notes": notes,
    }


def _holding(
    symbol: str = "AAA",
    quantity: float = 1,
    currency: str = "EUR",
    snapshot_date: date | None = None,
    account_id: str = "",
) -> dict:
    return {
        "account_id": account_id,
        "symbol": symbol,
        "currency": currency,
        "total_quantity": quantity,
        "total_cost_eur": 0,
        "snapshot_date": snapshot_date or date.today(),
    }


def test_performance_security_filter_excludes_crypto_accounts_and_symbols(
    monkeypatch,
):
    monkeypatch.setattr(
        portfolio.symbol_metadata_service,
        "is_crypto",
        lambda symbol: symbol == "TOKEN",
    )

    assert portfolio._include_performance_security(
        "stock-account",
        "MSFT",
        {"crypto-account"},
    )
    assert not portfolio._include_performance_security(
        "crypto-account",
        "UNMAPPED",
        {"crypto-account"},
    )
    assert not portfolio._include_performance_security(
        "stock-account",
        "TOKEN",
        {"crypto-account"},
    )


def test_uses_total_return_benchmark_and_common_zero_baseline(monkeypatch):
    start = date.today() - timedelta(days=4)
    dates = [start, start + timedelta(days=1), start + timedelta(days=2)]
    captured: dict = {}

    def fake_download(tickers, **kwargs):
        captured["tickers"] = tickers
        captured["kwargs"] = kwargs
        return _market_frame(
            dates,
            {
                "AAA": [100, 110, 121],
                portfolio.BENCHMARK_TICKER: [200, 220, 242],
                "EURUSD=X": [2, 2, 2],
            },
        )

    monkeypatch.setattr(portfolio.yf, "download", fake_download)

    response = portfolio._compute_performance_sync(
        [_transaction("AAA", start, 1)],
        [_holding()],
        "all",
    )

    assert portfolio.BENCHMARK_TICKER in captured["tickers"]
    assert "^GSPC" not in captured["tickers"]
    assert captured["kwargs"]["auto_adjust"] is False
    assert captured["kwargs"]["actions"] is True
    assert response.benchmark_name == "S&P 500 Total Return"
    assert "raw closes for market-value weights" in response.methodology
    assert [point.portfolio_return_pct for point in response.data] == [0.0, 10.0, 21.0]
    assert [point.sp500_return_pct for point in response.data] == [0.0, 10.0, 21.0]


def test_finite_period_ignores_unpriced_positions_closed_before_window(monkeypatch):
    today = date.today()
    period_start = today - timedelta(days=30)
    captured: dict[str, list[str]] = {}

    def fake_download(tickers, **_kwargs):
        captured["tickers"] = list(tickers)
        return _market_frame(
            [period_start, today],
            {
                "AAA": [100, 110],
                "OLD": [50, 50],
                portfolio.BENCHMARK_TICKER: [200, 220],
                "EURUSD=X": [2, 2],
            },
            adjusted_series={
                "AAA": [100, 110],
                "OLD": [None, None],
                portfolio.BENCHMARK_TICKER: [200, 220],
                "EURUSD=X": [2, 2],
            },
        )

    monkeypatch.setattr(portfolio.yf, "download", fake_download)

    response = portfolio._compute_performance_sync(
        [
            _transaction("OLD", today - timedelta(days=100), 1),
            _transaction(
                "OLD",
                today - timedelta(days=90),
                1,
                transaction_type="sell",
            ),
            _transaction("AAA", period_start, 1),
        ],
        [_holding("AAA")],
        "1m",
    )

    assert "OLD" not in captured["tickers"]
    assert response.data[-1].portfolio_return_pct == 10


def test_finite_period_ignores_priceable_positions_closed_before_window(monkeypatch):
    today = date.today()
    period_start = today - timedelta(days=30)
    captured: dict[str, list[str]] = {}

    def fake_download(tickers, **_kwargs):
        captured["tickers"] = list(tickers)
        return _market_frame(
            [period_start, today],
            {
                "AAA": [100, 110],
                "OLD": [50, 55],
                portfolio.BENCHMARK_TICKER: [200, 220],
                "EURUSD=X": [2, 2],
            },
        )

    monkeypatch.setattr(portfolio.yf, "download", fake_download)

    response = portfolio._compute_performance_sync(
        [
            _transaction("OLD", today - timedelta(days=100), 1),
            _transaction(
                "OLD",
                today - timedelta(days=90),
                1,
                transaction_type="sell",
            ),
            _transaction("AAA", period_start, 1),
        ],
        [_holding("AAA")],
        "1m",
    )

    assert "OLD" not in captured["tickers"]
    assert response.data[-1].portfolio_return_pct == 10


def test_finite_period_warns_and_omits_unreconciled_orphan_history(monkeypatch):
    today = date.today()
    period_start = today - timedelta(days=30)

    monkeypatch.setattr(
        portfolio.yf,
        "download",
        lambda *_args, **_kwargs: _market_frame(
            [period_start, today],
            {
                "AAA": [100, 110],
                "ORPHAN": [40, 40],
                portfolio.BENCHMARK_TICKER: [200, 220],
                "EURUSD=X": [2, 2],
            },
        ),
    )

    response = portfolio._compute_performance_sync(
        [
            _transaction("AAA", period_start, 1),
            _transaction("ORPHAN", period_start, 1),
        ],
        [_holding("AAA")],
        "1m",
    )

    assert response.warnings == [
        "Omitted incomplete transaction histories for ORPHAN because they do "
        "not reconcile to the current holdings snapshot."
    ]
    assert response.data[-1].portfolio_return_pct == 10


def test_finite_period_omits_two_sided_history_that_does_not_reconcile(
    monkeypatch,
):
    today = date.today()
    period_start = today - timedelta(days=30)

    monkeypatch.setattr(
        portfolio.yf,
        "download",
        lambda *_args, **_kwargs: _market_frame(
            [period_start, today],
            {
                "AAA": [100, 110],
                "ORPHAN": [40, 40],
                portfolio.BENCHMARK_TICKER: [200, 220],
                "EURUSD=X": [2, 2],
            },
        ),
    )

    response = portfolio._compute_performance_sync(
        [
            _transaction("AAA", period_start, 1),
            _transaction("ORPHAN", period_start, 2),
            _transaction(
                "ORPHAN",
                today,
                1,
                transaction_type="sell",
            ),
        ],
        [_holding("AAA")],
        "1m",
    )

    assert response.warnings == [
        "Omitted incomplete transaction histories for ORPHAN because they do "
        "not reconcile to the current holdings snapshot."
    ]
    assert response.data[-1].portfolio_return_pct == 10


def test_unpriced_split_imbalanced_orphan_still_fails_closed(monkeypatch):
    today = date.today()
    period_start = today - timedelta(days=30)

    monkeypatch.setattr(
        portfolio.yf,
        "download",
        lambda *_args, **_kwargs: _market_frame(
            [period_start, today],
            {
                "AAA": [100, 110],
                portfolio.BENCHMARK_TICKER: [200, 220],
                "EURUSD=X": [2, 2],
            },
        ),
    )

    with pytest.raises(
        portfolio.PerformanceDataUnavailableError,
        match="Historical prices are unavailable for CLOSED",
    ):
        portfolio._compute_performance_sync(
            [
                _transaction("AAA", period_start, 1),
                _transaction("CLOSED", period_start, 1),
                _transaction(
                    "CLOSED",
                    today,
                    2,
                    transaction_type="sell",
                ),
            ],
            [_holding("AAA")],
            "1m",
        )


def test_finite_period_requires_prices_for_closed_in_window_history(monkeypatch):
    today = date.today()
    period_start = today - timedelta(days=30)

    monkeypatch.setattr(
        portfolio.yf,
        "download",
        lambda *_args, **_kwargs: _market_frame(
            [period_start, today],
            {
                "AAA": [100, 110],
                portfolio.BENCHMARK_TICKER: [200, 220],
                "EURUSD=X": [2, 2],
            },
        ),
    )

    with pytest.raises(
        portfolio.PerformanceDataUnavailableError,
        match="Historical prices are unavailable for CLOSED",
    ):
        portfolio._compute_performance_sync(
            [
                _transaction("AAA", period_start, 1),
                _transaction("CLOSED", period_start, 1),
                _transaction(
                    "CLOSED",
                    today,
                    1,
                    transaction_type="sell",
                ),
            ],
            [_holding("AAA")],
            "1m",
        )


def test_finite_period_keeps_split_reconciled_closed_history(monkeypatch):
    today = date.today()
    period_start = today - timedelta(days=30)
    split_date = period_start + timedelta(days=1)
    raw = _market_frame(
        [period_start, split_date, today],
        {
            "CLOSED": [50, 55, 60],
            portfolio.BENCHMARK_TICKER: [200, 210, 220],
            "EURUSD=X": [2, 2, 2],
        },
        adjusted_series={
            "CLOSED": [50, 55, 60],
            portfolio.BENCHMARK_TICKER: [200, 210, 220],
            "EURUSD=X": [2, 2, 2],
        },
    )
    raw[("Stock Splits", "CLOSED")] = [0, 2, 0]
    raw = raw.sort_index(axis=1)
    monkeypatch.setattr(
        portfolio.yf,
        "download",
        lambda *_args, **_kwargs: raw,
    )

    response = portfolio._compute_performance_sync(
        [
            _transaction("CLOSED", period_start, 1),
            _transaction(
                "CLOSED",
                today,
                2,
                transaction_type="sell",
            ),
        ],
        [],
        "1m",
    )

    assert response.warnings == []
    assert response.data[-1].portfolio_return_pct == 20


def test_finite_period_keeps_split_affected_zero_raw_holding(monkeypatch):
    today = date.today()
    period_start = today - timedelta(days=30)
    buy_date = today - timedelta(days=40)
    split_date = today - timedelta(days=35)
    sell_date = today - timedelta(days=31)
    dates = [buy_date, split_date, sell_date, period_start, today]
    raw = _market_frame(
        dates,
        {
            "AAA": [100, 55, 56, 57, 60],
            portfolio.BENCHMARK_TICKER: [190, 195, 198, 200, 220],
            "EURUSD=X": [2, 2, 2, 2, 2],
        },
        adjusted_series={
            "AAA": [50, 55, 56, 57, 60],
            portfolio.BENCHMARK_TICKER: [190, 195, 198, 200, 220],
            "EURUSD=X": [2, 2, 2, 2, 2],
        },
    )
    raw[("Stock Splits", "AAA")] = [0, 2, 0, 0, 0]
    raw = raw.sort_index(axis=1)
    monkeypatch.setattr(
        portfolio.yf,
        "download",
        lambda *_args, **_kwargs: raw,
    )

    response = portfolio._compute_performance_sync(
        [
            _transaction("AAA", buy_date, 1),
            _transaction("AAA", sell_date, 1, transaction_type="sell"),
        ],
        [_holding("AAA", quantity=0, snapshot_date=buy_date)],
        "1m",
    )

    assert response.data[0].portfolio_value_eur == 57
    assert response.data[-1].portfolio_return_pct == pytest.approx(5.26)


def test_finite_period_ignores_zero_holding_without_position_history(monkeypatch):
    today = date.today()
    period_start = today - timedelta(days=30)
    captured: dict[str, list[str]] = {}

    def fake_download(tickers, **_kwargs):
        captured["tickers"] = list(tickers)
        return _market_frame(
            [period_start, today],
            {
                "AAA": [100, 110],
                portfolio.BENCHMARK_TICKER: [200, 220],
                "EURUSD=X": [2, 2],
            },
        )

    monkeypatch.setattr(portfolio.yf, "download", fake_download)

    response = portfolio._compute_performance_sync(
        [_transaction("AAA", period_start, 1)],
        [
            _holding("AAA"),
            _holding("DEAD", quantity=0),
        ],
        "1m",
    )

    assert "DEAD" not in captured["tickers"]
    assert response.data[-1].portfolio_return_pct == 10


def test_zero_holding_snapshot_fetches_older_split_for_later_sale(monkeypatch):
    today = date.today()
    period_start = today - timedelta(days=30)
    snapshot_date = today - timedelta(days=100)
    split_date = today - timedelta(days=60)
    sale_date = today - timedelta(days=10)
    download_start = period_start - timedelta(days=portfolio._PRICE_LOOKBACK_DAYS)
    main_raw = _market_frame(
        [period_start, sale_date, today],
        {
            "AAA": [60, 65, 70],
            portfolio.BENCHMARK_TICKER: [200, 210, 220],
            "EURUSD=X": [2, 2, 2],
        },
    )
    old_actions = _market_frame(
        [snapshot_date, split_date, download_start - timedelta(days=1)],
        {"AAA": [100, 55, 58]},
    )
    old_actions[("Stock Splits", "AAA")] = [0, 2, 0]
    old_actions = old_actions.sort_index(axis=1)
    requested_starts: list[str] = []

    def fake_download(_tickers, **kwargs):
        requested_starts.append(kwargs["start"])
        return old_actions if kwargs["start"] == str(snapshot_date) else main_raw

    monkeypatch.setattr(portfolio.yf, "download", fake_download)

    response = portfolio._compute_performance_sync(
        [
            _transaction(
                "AAA",
                sale_date,
                1,
                transaction_type="sell",
            )
        ],
        [_holding("AAA", quantity=0, snapshot_date=snapshot_date)],
        "1m",
    )

    assert requested_starts == [str(download_start), str(snapshot_date)]
    assert response.data[0].date == period_start
    assert response.data[-1].portfolio_value_eur == 70
    assert response.data[-1].portfolio_return_pct == pytest.approx(16.67)


def test_all_period_ignores_zero_quantity_position_symbols(monkeypatch):
    start = date.today() - timedelta(days=3)
    monkeypatch.setattr(
        portfolio.yf,
        "download",
        lambda *_args, **_kwargs: _market_frame(
            [start, date.today()],
            {
                "AAA": [100, 110],
                portfolio.BENCHMARK_TICKER: [200, 220],
                "EURUSD=X": [2, 2],
            },
        ),
    )

    response = portfolio._compute_performance_sync(
        [
            _transaction("AAA", start, 1),
            _transaction("ZERO", start, 0),
        ],
        [_holding("AAA")],
        "all",
    )

    assert response.data[-1].portfolio_return_pct == 10


def test_only_omitted_history_returns_its_warning(monkeypatch):
    today = date.today()
    period_start = today - timedelta(days=30)
    monkeypatch.setattr(
        portfolio.yf,
        "download",
        lambda *_args, **_kwargs: pytest.fail(
            "market data should not be requested for an omitted history"
        ),
    )

    response = portfolio._compute_performance_sync(
        [_transaction("ORPHAN", period_start, 1)],
        [],
        "1m",
    )

    assert response.data == []
    assert response.warnings == [
        "Omitted incomplete transaction histories for ORPHAN because they do "
        "not reconcile to the current holdings snapshot."
    ]


def test_future_dated_orphan_still_fails_closed():
    with pytest.raises(
        portfolio.PerformanceDataUnavailableError,
        match="ORPHAN has a future-dated position change",
    ):
        portfolio._compute_performance_sync(
            [
                _transaction(
                    "ORPHAN",
                    date.today() + timedelta(days=1),
                    1,
                )
            ],
            [],
            "1m",
        )


def test_future_dated_zero_holding_snapshot_still_fails_closed():
    with pytest.raises(
        portfolio.PerformanceDataUnavailableError,
        match="ZERO has a future-dated holding snapshot",
    ):
        portfolio._compute_performance_sync(
            [],
            [
                _holding(
                    "ZERO",
                    quantity=0,
                    snapshot_date=date.today() + timedelta(days=1),
                )
            ],
            "1m",
        )


def test_weights_total_returns_by_actual_market_value(monkeypatch):
    start = date.today() - timedelta(days=3)
    dates = [start, start + timedelta(days=1)]

    monkeypatch.setattr(
        portfolio.yf,
        "download",
        lambda *_args, **_kwargs: _market_frame(
            dates,
            {
                "AAA": [100, 110],
                "BBB": [100, 100],
                portfolio.BENCHMARK_TICKER: [200, 200],
                "EURUSD=X": [1, 1],
            },
            adjusted_series={
                "AAA": [10, 11],
                "BBB": [1000, 1000],
                portfolio.BENCHMARK_TICKER: [200, 200],
                "EURUSD=X": [1, 1],
            },
        ),
    )

    response = portfolio._compute_performance_sync(
        [
            _transaction("AAA", start, 9),
            _transaction("BBB", start, 1),
        ],
        [
            _holding("AAA", quantity=9),
            _holding("BBB", quantity=1),
        ],
        "all",
    )

    assert response.data[-1].portfolio_value_eur == pytest.approx(1090)
    assert response.data[-1].portfolio_return_pct == pytest.approx(9)


def test_fails_when_positive_holding_has_no_usable_price(monkeypatch):
    start = date.today() - timedelta(days=3)
    dates = [start, start + timedelta(days=1)]

    monkeypatch.setattr(
        portfolio.yf,
        "download",
        lambda *_args, **_kwargs: _market_frame(
            dates,
            {
                "AAA": [None, None],
                portfolio.BENCHMARK_TICKER: [200, 200],
            },
        ),
    )

    with pytest.raises(
        portfolio.PerformanceDataUnavailableError,
        match="Historical prices for AAA are unavailable",
    ):
        portfolio._compute_performance_sync(
            [_transaction("AAA", start, 1)],
            [_holding("AAA")],
            "all",
        )


def test_cash_flow_does_not_create_an_artificial_return(monkeypatch):
    start = date.today() - timedelta(days=4)
    dates = [start, start + timedelta(days=1), start + timedelta(days=2)]

    monkeypatch.setattr(
        portfolio.yf,
        "download",
        lambda *_args, **_kwargs: _market_frame(
            dates,
            {
                "AAA": [100, 110, 121],
                portfolio.BENCHMARK_TICKER: [200, 200, 200],
                "EURUSD=X": [2, 2, 2],
            },
        ),
    )

    response = portfolio._compute_performance_sync(
        [
            _transaction("AAA", start, 1),
            _transaction("AAA", dates[1], 1),
        ],
        [_holding(quantity=2)],
        "all",
    )

    assert [point.portfolio_value_eur for point in response.data] == [100.0, 220.0, 242.0]
    assert [point.portfolio_return_pct for point in response.data] == [0.0, 10.0, 21.0]


def test_portfolio_and_benchmark_are_both_converted_to_eur(monkeypatch):
    start = date.today() - timedelta(days=3)
    dates = [start, start + timedelta(days=1)]

    monkeypatch.setattr(
        portfolio.yf,
        "download",
        lambda *_args, **_kwargs: _market_frame(
            dates,
            {
                "AAA": [100, 100],
                portfolio.BENCHMARK_TICKER: [200, 200],
                "EURUSD=X": [2, 1],
            },
        ),
    )

    response = portfolio._compute_performance_sync(
        [_transaction("AAA", start, 1, currency="USD")],
        [_holding(currency="USD")],
        "all",
    )

    assert [point.portfolio_return_pct for point in response.data] == [0.0, 100.0]
    assert [point.sp500_return_pct for point in response.data] == [0.0, 100.0]


def test_pre_split_transactions_use_current_share_basis(monkeypatch):
    start = date.today() - timedelta(days=4)
    split_date = start + timedelta(days=1)
    final_date = start + timedelta(days=2)
    raw = _market_frame(
        [start, split_date, final_date],
        {
            "AAA": [50, 55, 60],
            portfolio.BENCHMARK_TICKER: [100, 110, 120],
            "EURUSD=X": [2, 2, 2],
        },
        adjusted_series={
            "AAA": [50, 55, 60],
            portfolio.BENCHMARK_TICKER: [100, 110, 120],
            "EURUSD=X": [2, 2, 2],
        },
    )
    raw[("Stock Splits", "AAA")] = [0, 2, 0]
    raw = raw.sort_index(axis=1)
    monkeypatch.setattr(
        portfolio.yf,
        "download",
        lambda *_args, **_kwargs: raw,
    )

    response = portfolio._compute_performance_sync(
        [_transaction("AAA", start, 1)],
        [_holding(quantity=2, snapshot_date=final_date)],
        "all",
    )

    assert response.warnings == []
    assert [point.portfolio_value_eur for point in response.data] == [
        100.0,
        110.0,
        120.0,
    ]
    assert response.data[-1].portfolio_return_pct == 20.0


def test_nordnet_lot_quantities_are_not_split_adjusted_twice(monkeypatch):
    start = date.today() - timedelta(days=4)
    split_date = start + timedelta(days=1)
    final_date = start + timedelta(days=2)
    raw = _market_frame(
        [start, split_date, final_date],
        {
            "AAA": [50, 55, 60],
            portfolio.BENCHMARK_TICKER: [100, 110, 120],
            "EURUSD=X": [2, 2, 2],
        },
        adjusted_series={
            "AAA": [50, 55, 60],
            portfolio.BENCHMARK_TICKER: [100, 110, 120],
            "EURUSD=X": [2, 2, 2],
        },
    )
    raw[("Stock Splits", "AAA")] = [0, 2, 0]
    raw = raw.sort_index(axis=1)
    monkeypatch.setattr(
        portfolio.yf,
        "download",
        lambda *_args, **_kwargs: raw,
    )

    response = portfolio._compute_performance_sync(
        [
            _transaction(
                "AAA",
                start,
                2,
                notes=(
                    "Imported from Nordnet lot export "
                    f"({final_date.isoformat()})"
                ),
            )
        ],
        [_holding(quantity=2, snapshot_date=final_date)],
        "all",
    )

    assert response.warnings == []
    assert response.data[0].portfolio_value_eur == 100.0


def test_bonus_issue_adjustment_and_duplicate_split_are_not_double_counted(
    monkeypatch,
):
    start = date.today() - timedelta(days=6)
    split_date = start + timedelta(days=1)
    bonus_record_date = start + timedelta(days=3)
    later_buy_date = start + timedelta(days=4)
    final_date = start + timedelta(days=5)
    raw = _market_frame(
        [start, split_date, bonus_record_date, later_buy_date, final_date],
        {
            "AAA": [8, 8.1, 8, 8.1, 8.2],
            portfolio.BENCHMARK_TICKER: [100, 101, 102, 103, 104],
            "EURUSD=X": [2, 2, 2, 2, 2],
        },
    )
    raw[("Stock Splits", "AAA")] = [0, 5, 4, 0, 0]
    raw = raw.sort_index(axis=1)
    monkeypatch.setattr(
        portfolio.yf,
        "download",
        lambda *_args, **_kwargs: raw,
    )

    response = portfolio._compute_performance_sync(
        [
            _transaction("AAA", start, 201),
            _transaction(
                "AAA",
                split_date,
                804,
                notes="Position adjustment: RAHASTOANTI AP JÄTTÖ",
            ),
            _transaction("AAA", later_buy_date, 158),
        ],
        [_holding("AAA", quantity=1163, snapshot_date=start)],
        "all",
    )

    assert response.warnings == []
    assert response.data[-1].portfolio_value_eur == pytest.approx(9536.6)


def test_finite_period_fetches_splits_older_than_price_window(monkeypatch):
    today = date.today()
    period_start = today - timedelta(days=30)
    aaa_purchase = today - timedelta(days=365)
    bbb_purchase = today - timedelta(days=100)
    split_date = today - timedelta(days=180)
    download_start = period_start - timedelta(days=portfolio._PRICE_LOOKBACK_DAYS)
    main_raw = _market_frame(
        [period_start, today],
        {
            "AAA": [50, 100],
            "BBB": [100, 100],
            portfolio.BENCHMARK_TICKER: [200, 220],
            "EURUSD=X": [2, 2],
        },
    )
    main_raw[("Stock Splits", "AAA")] = [0, 0]
    main_raw[("Stock Splits", "BBB")] = [0, 0]
    main_raw = main_raw.sort_index(axis=1)
    old_actions = _market_frame(
        [aaa_purchase, split_date, download_start - timedelta(days=1)],
        {
            "AAA": [100, 50, 60],
            "BBB": [80, 90, 100],
        },
    )
    old_actions[("Stock Splits", "AAA")] = [0, 2, 0]
    old_actions[("Stock Splits", "BBB")] = [0, 0, 0]
    old_actions = old_actions.sort_index(axis=1)

    def fake_download(_tickers, **kwargs):
        return old_actions if kwargs["start"] == str(aaa_purchase) else main_raw

    monkeypatch.setattr(portfolio.yf, "download", fake_download)

    response = portfolio._compute_performance_sync(
        [
            _transaction("AAA", aaa_purchase, 1),
            _transaction("BBB", bbb_purchase, 1),
        ],
        [
            _holding("AAA", quantity=2),
            _holding("BBB", quantity=1),
        ],
        "1m",
    )

    assert response.warnings == []
    assert response.data[-1].portfolio_return_pct == 50.0


def test_partial_historical_split_download_fails_closed(monkeypatch):
    today = date.today()
    purchase_date = today - timedelta(days=365)
    period_start = today - timedelta(days=30)
    download_start = period_start - timedelta(days=portfolio._PRICE_LOOKBACK_DAYS)
    main_raw = _market_frame(
        [period_start, today],
        {
            "AAA": [100, 110],
            portfolio.BENCHMARK_TICKER: [200, 220],
            "EURUSD=X": [2, 2],
        },
    )
    old_actions = _market_frame(
        [purchase_date, download_start - timedelta(days=1)],
        {"AAA": [100, 110]},
    )
    old_actions[("Stock Splits", "AAA")] = [None, None]

    def fake_download(_tickers, **kwargs):
        return old_actions if kwargs["start"] == str(purchase_date) else main_raw

    monkeypatch.setattr(portfolio.yf, "download", fake_download)

    with pytest.raises(
        portfolio.PerformanceDataUnavailableError,
        match="Historical stock-split data is unavailable for AAA",
    ):
        portfolio._compute_performance_sync(
            [_transaction("AAA", purchase_date, 1)],
            [_holding("AAA")],
            "1m",
        )


def test_truncated_historical_split_download_fails_closed(monkeypatch):
    today = date.today()
    purchase_date = today - timedelta(days=365)
    period_start = today - timedelta(days=30)
    download_start = period_start - timedelta(days=portfolio._PRICE_LOOKBACK_DAYS)
    main_raw = _market_frame(
        [period_start, today],
        {
            "AAA": [100, 110],
            portfolio.BENCHMARK_TICKER: [200, 220],
            "EURUSD=X": [2, 2],
        },
    )
    old_actions = _market_frame(
        [
            purchase_date + timedelta(days=30),
            download_start - timedelta(days=1),
        ],
        {"AAA": [100, 110]},
    )

    def fake_download(_tickers, **kwargs):
        return old_actions if kwargs["start"] == str(purchase_date) else main_raw

    monkeypatch.setattr(portfolio.yf, "download", fake_download)

    with pytest.raises(
        portfolio.PerformanceDataUnavailableError,
        match="Historical stock-split data is unavailable for AAA",
    ):
        portfolio._compute_performance_sync(
            [_transaction("AAA", purchase_date, 1)],
            [_holding("AAA")],
            "1m",
        )


def test_lookback_supplies_prior_close_for_market_holiday(monkeypatch):
    start = date.today() - timedelta(days=30)
    prior = start - timedelta(days=1)
    dates = [prior, start, start + timedelta(days=1), date.today()]
    raw = _market_frame(
        dates,
        {
            "AAA": [100, None, 110, 110],
            portfolio.BENCHMARK_TICKER: [190, 200, 220, 220],
            "EURUSD=X": [2, 2, 2, 2],
        },
    )
    raw[("Stock Splits", "AAA")] = [0, 0, 0, 0]
    raw = raw.sort_index(axis=1)

    monkeypatch.setattr(
        portfolio.yf,
        "download",
        lambda *_args, **_kwargs: raw,
    )

    response = portfolio._compute_performance_sync(
        [_transaction("AAA", prior, 1)],
        [_holding()],
        "1m",
    )

    assert [point.date for point in response.data] == [start, dates[2], date.today()]
    assert [point.portfolio_return_pct for point in response.data] == [0.0, 10.0, 10.0]
    assert [point.sp500_return_pct for point in response.data] == [0.0, 10.0, 10.0]


def test_foreign_market_period_start_is_used_as_return_baseline(monkeypatch):
    start = date.today() - timedelta(days=30)
    prior = start - timedelta(days=1)
    next_session = start + timedelta(days=1)
    monkeypatch.setattr(
        portfolio.yf,
        "download",
        lambda *_args, **_kwargs: _market_frame(
            [prior, start, next_session, date.today()],
            {
                "AAA": [95, 100, 110, 110],
                portfolio.BENCHMARK_TICKER: [200, None, 200, 220],
                "EURUSD=X": [2, 2, 2, 2],
            },
        ),
    )

    response = portfolio._compute_performance_sync(
        [_transaction("AAA", prior, 1)],
        [_holding("AAA")],
        "1m",
    )

    assert [point.date for point in response.data] == [
        start,
        next_session,
        date.today(),
    ]
    assert [point.portfolio_return_pct for point in response.data] == [
        0.0,
        10.0,
        10.0,
    ]


def test_snapshot_without_same_day_close_uses_fresh_prior_close(monkeypatch):
    start = date.today() - timedelta(days=4)
    latest_close = date.today() - timedelta(days=1)
    monkeypatch.setattr(
        portfolio.yf,
        "download",
        lambda *_args, **_kwargs: _market_frame(
            [start, latest_close],
            {
                "AAA": [100, 110],
                "BBB": [50, 50],
                portfolio.BENCHMARK_TICKER: [200, 220],
                "EURUSD=X": [2, 2],
            },
        ),
    )

    response = portfolio._compute_performance_sync(
        [_transaction("AAA", start, 1)],
        [
            _holding("AAA", snapshot_date=date.today()),
            _holding("BBB", snapshot_date=date.today()),
        ],
        "all",
    )

    assert response.data[-1].date == latest_close
    assert response.data[-1].portfolio_value_eur == 160
    assert response.data[-1].portfolio_return_pct == 10


def test_one_sided_adjusted_close_gap_fails_closed(monkeypatch):
    start = date.today() - timedelta(days=3)
    dates = [start, start + timedelta(days=1), date.today()]
    monkeypatch.setattr(
        portfolio.yf,
        "download",
        lambda *_args, **_kwargs: _market_frame(
            dates,
            {
                "AAA": [100, 110, 112],
                portfolio.BENCHMARK_TICKER: [200, 210, 220],
                "EURUSD=X": [2, 2, 2],
            },
            adjusted_series={
                "AAA": [100, None, 112],
                portfolio.BENCHMARK_TICKER: [200, 210, 220],
                "EURUSD=X": [2, 2, 2],
            },
        ),
    )

    with pytest.raises(
        portfolio.PerformanceDataUnavailableError,
        match="Raw and adjusted historical prices for AAA are inconsistent",
    ):
        portfolio._compute_performance_sync(
            [_transaction("AAA", start, 1)],
            [_holding("AAA")],
            "all",
        )


def test_non_benchmark_start_date_is_kept_as_visible_zero_baseline(monkeypatch):
    start = date.today() - timedelta(days=4)
    prior = start - timedelta(days=1)
    dates = [prior, start, start + timedelta(days=1), start + timedelta(days=2)]

    monkeypatch.setattr(
        portfolio.yf,
        "download",
        lambda *_args, **_kwargs: _market_frame(
            dates,
            {
                "AAA": [95, 100, 101, 110],
                portfolio.BENCHMARK_TICKER: [190, None, 200, 220],
                "EURUSD=X": [2, 2, 2, 2],
            },
        ),
    )

    response = portfolio._compute_performance_sync(
        [_transaction("AAA", start, 1)],
        [_holding()],
        "all",
    )

    assert [point.date for point in response.data] == dates[1:]
    assert response.data[0].portfolio_return_pct == 0.0
    assert response.data[0].sp500_return_pct == 0.0
    assert response.data[-1].portfolio_return_pct == 10.0
    assert response.data[-1].sp500_return_pct == pytest.approx(15.79)


def test_trade_on_non_benchmark_session_is_included_in_twrr(monkeypatch):
    start = date.today() - timedelta(days=4)
    dates = [start, start + timedelta(days=1), start + timedelta(days=2)]

    monkeypatch.setattr(
        portfolio.yf,
        "download",
        lambda *_args, **_kwargs: _market_frame(
            dates,
            {
                "AAA": [100, 110, 121],
                portfolio.BENCHMARK_TICKER: [200, None, 220],
                "EURUSD=X": [2, 2, 2],
            },
        ),
    )

    response = portfolio._compute_performance_sync(
        [
            _transaction("AAA", start, 1),
            _transaction("AAA", dates[1], 1),
        ],
        [_holding(quantity=2)],
        "all",
    )

    assert [point.date for point in response.data] == [start, dates[2]]
    assert response.data[-1].portfolio_return_pct == 21.0
    assert response.data[-1].sp500_return_pct == 10.0


def test_missing_required_fx_data_fails_instead_of_using_one_to_one(monkeypatch):
    start = date.today() - timedelta(days=3)
    dates = [start, start + timedelta(days=1)]

    monkeypatch.setattr(
        portfolio.yf,
        "download",
        lambda *_args, **_kwargs: _market_frame(
            dates,
            {
                "AAA": [100, 110],
                portfolio.BENCHMARK_TICKER: [200, 220],
                "EURUSD=X": [2, 2],
            },
        ),
    )

    with pytest.raises(
        portfolio.PerformanceDataUnavailableError,
        match="EUR/SEK exchange-rate history is unavailable",
    ):
        portfolio._compute_performance_sync(
            [_transaction("AAA", start, 1, currency="SEK")],
            [_holding(currency="SEK")],
            "all",
        )


def test_stale_fx_data_fails_instead_of_being_forward_filled_forever(monkeypatch):
    start = date.today() - timedelta(days=10)
    dates = [start + timedelta(days=offset) for offset in range(10)]

    monkeypatch.setattr(
        portfolio.yf,
        "download",
        lambda *_args, **_kwargs: _market_frame(
            dates,
            {
                "AAA": [100 + offset for offset in range(10)],
                portfolio.BENCHMARK_TICKER: [200 + offset for offset in range(10)],
                "EURUSD=X": [2, *([None] * 9)],
            },
        ),
    )

    with pytest.raises(
        portfolio.PerformanceDataUnavailableError,
        match="EUR/USD exchange-rate history is unavailable or stale",
    ):
        portfolio._compute_performance_sync(
            [_transaction("AAA", start, 1)],
            [_holding()],
            "all",
        )


def test_all_nan_benchmark_fails_instead_of_returning_cached_empty_data(monkeypatch):
    start = date.today() - timedelta(days=3)
    dates = [start, start + timedelta(days=1)]

    monkeypatch.setattr(
        portfolio.yf,
        "download",
        lambda *_args, **_kwargs: _market_frame(
            dates,
            {
                "AAA": [100, 110],
                portfolio.BENCHMARK_TICKER: [None, None],
                "EURUSD=X": [2, 2],
            },
        ),
    )

    with pytest.raises(
        portfolio.PerformanceDataUnavailableError,
        match="returned no usable observations",
    ):
        portfolio._compute_performance_sync(
            [_transaction("AAA", start, 1)],
            [_holding()],
            "all",
        )


def test_stale_benchmark_fails_instead_of_returning_an_old_chart(monkeypatch):
    stale_date = date.today() - timedelta(days=10)
    monkeypatch.setattr(
        portfolio.yf,
        "download",
        lambda *_args, **_kwargs: _market_frame(
            [stale_date, date.today()],
            {
                "AAA": [100, 110],
                portfolio.BENCHMARK_TICKER: [200, None],
                "EURUSD=X": [2, 2],
            },
        ),
    )

    with pytest.raises(
        portfolio.PerformanceDataUnavailableError,
        match="data is more than 7 days stale",
    ):
        portfolio._compute_performance_sync(
            [_transaction("AAA", stale_date, 1)],
            [_holding()],
            "all",
        )


def test_holding_without_transactions_starts_at_its_snapshot(monkeypatch):
    snapshot_date = date.today() - timedelta(days=2)
    final_date = date.today()
    monkeypatch.setattr(
        portfolio.yf,
        "download",
        lambda *_args, **_kwargs: _market_frame(
            [snapshot_date, final_date],
            {
                "AAA": [100, 110],
                portfolio.BENCHMARK_TICKER: [200, 220],
                "EURUSD=X": [2, 2],
            },
        ),
    )

    response = portfolio._compute_performance_sync(
        [],
        [_holding(quantity=10, snapshot_date=snapshot_date)],
        "all",
    )

    assert response.start_date == snapshot_date
    assert [point.portfolio_return_pct for point in response.data] == [0.0, 10.0]


def test_opening_balance_reconciliation_aggregates_duplicate_holdings():
    start = date.today() - timedelta(days=30)
    transactions = [_transaction("AAA", start, 10)]
    holdings = [
        {
            "symbol": "AAA",
            "currency": "EUR",
            "total_quantity": 10,
            "total_cost_eur": 1_000,
            "snapshot_date": start,
        },
        {
            "symbol": "AAA",
            "currency": "EUR",
            "total_quantity": 5,
            "total_cost_eur": 500,
            "snapshot_date": start,
        },
    ]

    warnings = portfolio._add_opening_balance_transactions(transactions, holdings)

    assert len(transactions) == 2
    assert transactions[-1]["quantity"] == 5
    assert transactions[-1]["date"] == start
    assert warnings == [
        "AAA: inferred the remaining opening balance at the "
        f"{start.isoformat()} holding snapshot; performance before that date "
        "excludes those shares."
    ]


def test_missing_buys_before_sale_use_minimum_pre_history_balance():
    sale_date = date.today() - timedelta(days=30)
    snapshot_date = date.today() - timedelta(days=5)
    transactions = [
        _transaction("AAA", sale_date, 20, transaction_type="sell"),
    ]
    holdings = [
        {
            "symbol": "AAA",
            "currency": "EUR",
            "total_quantity": 100,
            "total_cost_eur": 10_000,
            "snapshot_date": snapshot_date,
        }
    ]

    warnings = portfolio._add_opening_balance_transactions(transactions, holdings)

    synthetic = transactions[1:]
    assert [(tx["date"], tx["quantity"]) for tx in synthetic] == [
        (sale_date, 20),
        (snapshot_date, 100),
    ]
    assert warnings == [
        "AAA: inferred the minimum opening balance needed to cover recorded "
        "sales; returns before the earliest recorded transaction cannot be verified.",
        "AAA: inferred the remaining opening balance at the "
        f"{snapshot_date.isoformat()} holding snapshot; performance before that "
        "date excludes those shares.",
    ]


def test_post_snapshot_sale_uses_full_snapshot_quantity(monkeypatch):
    snapshot_date = date.today() - timedelta(days=5)
    sale_date = date.today()
    monkeypatch.setattr(
        portfolio.yf,
        "download",
        lambda *_args, **_kwargs: _market_frame(
            [snapshot_date, sale_date],
            {
                "AAA": [100, 200],
                "BBB": [100, 100],
                portfolio.BENCHMARK_TICKER: [200, 220],
                "EURUSD=X": [2, 2],
            },
        ),
    )

    response = portfolio._compute_performance_sync(
        [
            _transaction(
                "AAA",
                sale_date,
                5,
                transaction_type="sell",
            )
        ],
        [
            _holding("AAA", quantity=5, snapshot_date=snapshot_date),
            _holding("BBB", quantity=10, snapshot_date=snapshot_date),
        ],
        "all",
    )

    assert response.data[-1].portfolio_return_pct == 50.0


def test_reconciled_sale_history_computes_without_negative_position(monkeypatch):
    sale_date = date.today() - timedelta(days=4)
    snapshot_date = date.today() - timedelta(days=2)
    final_date = date.today() - timedelta(days=1)
    transactions = [
        _transaction("AAA", sale_date, 20, transaction_type="sell"),
    ]
    holdings = [
        {
            "symbol": "AAA",
            "currency": "EUR",
            "total_quantity": 100,
            "total_cost_eur": 10_000,
            "snapshot_date": snapshot_date,
        }
    ]
    warnings = portfolio._add_opening_balance_transactions(transactions, holdings)
    monkeypatch.setattr(
        portfolio.yf,
        "download",
        lambda *_args, **_kwargs: _market_frame(
            [sale_date, snapshot_date, final_date],
            {
                "AAA": [90, 100, 110],
                portfolio.BENCHMARK_TICKER: [180, 200, 220],
                "EURUSD=X": [2, 2, 2],
            },
        ),
    )

    response = portfolio._compute_performance_sync(
        transactions,
        holdings,
        "all",
        warnings,
    )

    assert [point.date for point in response.data] == [snapshot_date, final_date]
    assert response.data[-1].portfolio_return_pct == 10.0


def test_irreconcilable_transaction_sequence_fails_closed():
    first_date = date.today() - timedelta(days=30)
    transactions = [
        _transaction("AAA", first_date, 20, transaction_type="sell"),
        _transaction("AAA", first_date + timedelta(days=1), 20),
    ]
    holdings = [
        {
            "symbol": "AAA",
            "currency": "EUR",
            "total_quantity": 0,
            "total_cost_eur": 0,
            "snapshot_date": date.today(),
        }
    ]

    with pytest.raises(
        portfolio.PerformanceDataUnavailableError,
        match="cannot be reconciled",
    ):
        portfolio._add_opening_balance_transactions(transactions, holdings)


def test_transactions_cannot_claim_shares_missing_from_current_holdings():
    start = date.today() - timedelta(days=30)

    with pytest.raises(
        portfolio.PerformanceDataUnavailableError,
        match="transactions for AAA exceed the holding quantity",
    ):
        portfolio._add_opening_balance_transactions(
            [_transaction("AAA", start, 1)],
            [],
        )


def test_missing_history_uses_holding_snapshot_not_unrelated_transaction_date():
    unrelated_date = date.today() - timedelta(days=365)
    snapshot_date = date.today() - timedelta(days=10)
    transactions = [_transaction("AAA", unrelated_date, 1)]
    holdings = [
        {
            "symbol": "AAA",
            "currency": "EUR",
            "total_quantity": 1,
            "total_cost_eur": 100,
            "snapshot_date": unrelated_date,
        },
        {
            "symbol": "BBB",
            "currency": "EUR",
            "total_quantity": 2,
            "total_cost_eur": 200,
            "snapshot_date": snapshot_date,
        },
    ]

    portfolio._add_opening_balance_transactions(transactions, holdings)

    assert transactions[-1]["symbol"] == "BBB"
    assert transactions[-1]["date"] == snapshot_date


def test_opening_balances_are_reconciled_per_account():
    old_snapshot = date.today() - timedelta(days=100)
    new_snapshot = date.today() - timedelta(days=10)
    transactions = [
        _transaction("AAA", old_snapshot, 10, account_id="account-a"),
    ]
    holdings = [
        _holding(
            quantity=10,
            snapshot_date=new_snapshot,
            account_id="account-a",
        ),
        _holding(
            quantity=5,
            snapshot_date=old_snapshot,
            account_id="account-b",
        ),
    ]

    portfolio._add_opening_balance_transactions(transactions, holdings)

    assert transactions[-1]["account_id"] == "account-b"
    assert transactions[-1]["quantity"] == 5
    assert transactions[-1]["date"] == old_snapshot


def test_source_fingerprint_changes_when_portfolio_data_changes():
    start = date.today() - timedelta(days=30)
    transactions = [_transaction("AAA", start, 1)]
    holdings = [
        {
            "symbol": "AAA",
            "currency": "EUR",
            "total_quantity": 1,
            "total_cost_eur": 100,
        }
    ]
    initial = portfolio._performance_source_fingerprint(transactions, holdings)

    transactions[0]["quantity"] = 2

    assert portfolio._performance_source_fingerprint(transactions, holdings) != initial


def test_statement_snapshot_date_uses_imported_report_period_end():
    assert portfolio._statement_snapshot_date(
        "Imported from Nordnet lot export (2025-03-31)"
    ) == date(2025, 3, 31)
    assert portfolio._statement_snapshot_date(
        "Fidelity espp_purchase (2025-01-01 - 2025-06-30)"
    ) == date(2025, 6, 30)
    assert portfolio._statement_snapshot_date("Manual transaction 2025-06-30") is None


def test_holding_snapshot_is_normalized_for_later_split():
    snapshot_date = date.today() - timedelta(days=10)
    split_date = date.today() - timedelta(days=5)
    split_events = pd.DataFrame(
        {"AAA": [2]},
        index=pd.to_datetime([split_date]),
    )

    adjusted = portfolio._adjust_holdings_for_splits(
        [_holding(quantity=3, snapshot_date=snapshot_date)],
        [],
        split_events,
        {"AAA": "AAA"},
    )

    assert adjusted[0]["total_quantity"] == 6


def test_holding_split_normalization_excludes_later_trade_quantity():
    snapshot_date = date.today() - timedelta(days=10)
    split_date = date.today() - timedelta(days=7)
    later_buy_date = date.today() - timedelta(days=5)
    split_events = pd.DataFrame(
        {"AAA": [2]},
        index=pd.to_datetime([split_date]),
    )

    adjusted = portfolio._adjust_holdings_for_splits(
        [_holding(quantity=2, snapshot_date=snapshot_date)],
        [_transaction("AAA", later_buy_date, 1)],
        split_events,
        {"AAA": "AAA"},
    )

    assert adjusted[0]["total_quantity"] == 3


def test_split_events_collapse_total_and_bonus_share_ratios():
    split_date = date.today() - timedelta(days=3)
    bonus_record_date = date.today() - timedelta(days=1)
    split_events = pd.DataFrame(
        {"AAA": [5, 4]},
        index=pd.to_datetime([split_date, bonus_record_date]),
    )

    adjusted = portfolio._deduplicate_split_events(split_events)

    assert adjusted["AAA"].tolist() == [5, 0]


def test_small_fractional_holding_is_not_ignored():
    snapshot_date = date.today() - timedelta(days=1)
    transactions: list[dict] = []

    portfolio._add_opening_balance_transactions(
        transactions,
        [_holding(quantity=0.005, snapshot_date=snapshot_date)],
    )

    assert transactions[0]["quantity"] == 0.005


def test_snapshot_without_fresh_prior_close_fails_closed(monkeypatch):
    snapshot_date = date.today() - timedelta(days=30)
    first_price_date = snapshot_date + timedelta(days=20)
    monkeypatch.setattr(
        portfolio.yf,
        "download",
        lambda *_args, **_kwargs: _market_frame(
            [snapshot_date, first_price_date, date.today()],
            {
                "AAA": [None, 100, 110],
                portfolio.BENCHMARK_TICKER: [200, 210, 220],
                "EURUSD=X": [2, 2, 2],
            },
        ),
    )

    with pytest.raises(
        portfolio.PerformanceDataUnavailableError,
        match="unavailable at its holding snapshot",
    ):
        portfolio._compute_performance_sync(
            [],
            [_holding("AAA", snapshot_date=snapshot_date)],
            "all",
        )


def test_future_holding_snapshot_fails_closed():
    with pytest.raises(
        portfolio.PerformanceDataUnavailableError,
        match="future-dated holding snapshot",
    ):
        portfolio._add_opening_balance_transactions(
            [],
            [_holding(snapshot_date=date.today() + timedelta(days=1))],
        )


@pytest.mark.asyncio
async def test_performance_cache_upsert_handles_concurrent_cold_writes(tmp_path):
    database_path = str(tmp_path / "performance-cache.db").replace("\\", "/")
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(CacheEntry.__table__.create)

    async def write_cache(value: str) -> None:
        async with session_factory() as session:
            await portfolio._upsert_performance_cache(
                session,
                "performance-v3-1y",
                value,
                datetime.utcnow() + timedelta(hours=1),
            )
            await session.commit()

    try:
        await asyncio.gather(write_cache("first"), write_cache("second"))
        async with session_factory() as session:
            entries = list(
                (
                    await session.execute(
                        select(CacheEntry).where(
                            CacheEntry.key == "performance-v3-1y"
                        )
                    )
                ).scalars()
            )
        assert len(entries) == 1
        assert entries[0].value in {"first", "second"}
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_transaction_free_fidelity_import_persists_statement_date(monkeypatch):
    period_end = date.today() - timedelta(days=30)
    parsed = FidelityParseResult(
        participant_number="participant",
        period_start=period_end - timedelta(days=90),
        period_end=period_end,
        account_value_usd=Decimal("100"),
        holdings=[
            FidelityHolding(
                symbol="MSFT",
                name="Microsoft",
                quantity=Decimal("1"),
                price_usd=Decimal("100"),
                market_value_usd=Decimal("100"),
                cost_basis_usd=Decimal("90"),
                unrealized_gain_usd=Decimal("10"),
            )
        ],
        transactions=[],
    )

    async def fake_parse(_content: bytes) -> FidelityParseResult:
        return parsed

    class FakeResult:
        @staticmethod
        def scalar_one_or_none():
            return None

    class FakeSession:
        def __init__(self):
            self.added: list[object] = []

        async def execute(self, _statement):
            return FakeResult()

        def add(self, value: object) -> None:
            self.added.append(value)

        async def flush(self) -> None:
            return None

    class FakeUpload:
        async def read(self) -> bytes:
            return b"statement"

    monkeypatch.setattr(upload_router, "parse_fidelity_pdf", fake_parse)
    session = FakeSession()

    await upload_router.upload_fidelity_pdf(FakeUpload(), session)

    holding = next(value for value in session.added if isinstance(value, Holding))
    assert holding.snapshot_date == period_end


@pytest.mark.asyncio
async def test_fidelity_overlap_merge_preserves_history_and_latest_snapshot(
    monkeypatch,
    tmp_path,
):
    database_path = str(tmp_path / "fidelity-merge.db").replace("\\", "/")
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        account = Account(
            name="Fidelity ESPP",
            broker="fidelity",
            account_type=AccountType.espp,
            external_id="participant",
            currency="USD",
            tax_treatment=TaxTreatment.espp,
        )
        session.add(account)
        await session.flush()
        session.add_all(
            [
                Holding(
                    account_id=account.id,
                    symbol="MSFT",
                    isin="US5949181045",
                    instrument_name="Microsoft",
                    currency="USD",
                    total_quantity=Decimal("5"),
                    snapshot_date=date(2025, 6, 30),
                    avg_cost_basis_eur=Decimal("90"),
                    total_cost_eur=Decimal("450"),
                ),
                Transaction(
                    account_id=account.id,
                    symbol="MSFT",
                    isin="US5949181045",
                    instrument_name="Microsoft",
                    currency="USD",
                    transaction_type=TransactionType.espp_purchase,
                    date=date(2025, 1, 15),
                    quantity=Decimal("1"),
                    price_native=Decimal("500"),
                    price_eur=Decimal("450"),
                    total_native=Decimal("500"),
                    total_eur=Decimal("450"),
                    notes=(
                        "Fidelity espp_purchase "
                        "(2025-01-01 - 2025-06-30)"
                    ),
                ),
                Transaction(
                    account_id=account.id,
                    symbol="CASH",
                    isin="",
                    instrument_name="Manual deposit",
                    currency="EUR",
                    transaction_type=TransactionType.deposit,
                    date=date(2024, 1, 1),
                    quantity=Decimal("0"),
                    price_native=Decimal("0"),
                    price_eur=Decimal("0"),
                    total_native=Decimal("100"),
                    total_eur=Decimal("100"),
                    notes="Manual entry",
                ),
            ]
        )
        await session.commit()

    def parsed_statement(december_amount: str) -> FidelityParseResult:
        return FidelityParseResult(
            participant_number="participant",
            period_start=date(2024, 7, 1),
            period_end=date(2025, 3, 31),
            account_value_usd=Decimal("200"),
            holdings=[
                FidelityHolding(
                    symbol="MSFT",
                    name="Microsoft",
                    quantity=Decimal("2"),
                    price_usd=Decimal("100"),
                    market_value_usd=Decimal("200"),
                    cost_basis_usd=Decimal("180"),
                    unrealized_gain_usd=Decimal("20"),
                )
            ],
            transactions=[
                FidelityTransaction(
                    date=date(2025, 1, 15),
                    symbol="MSFT",
                    name="Microsoft",
                    transaction_type="espp_purchase",
                    quantity=Decimal("1"),
                    price_usd=Decimal("500"),
                    amount_usd=Decimal("500"),
                    cost_basis_usd=None,
                ),
                FidelityTransaction(
                    date=date(2024, 12, 1),
                    symbol="MSFT",
                    name="Microsoft",
                    transaction_type="dividend",
                    quantity=None,
                    price_usd=None,
                    amount_usd=Decimal(december_amount),
                    cost_basis_usd=None,
                ),
            ],
        )

    current_statement = [parsed_statement("100")]

    async def fake_parse(_content: bytes) -> FidelityParseResult:
        return current_statement[0]

    async def fake_convert(_db, _symbol):
        return {"total_transactions": 0}

    class FakeUpload:
        async def read(self) -> bytes:
            return b"statement"

    monkeypatch.setattr(upload_router, "parse_fidelity_pdf", fake_parse)
    monkeypatch.setattr(
        upload_router.fx_convert,
        "convert_symbol_to_eur",
        fake_convert,
    )

    async with session_factory() as session:
        first = await upload_router.upload_fidelity_pdf(FakeUpload(), session)
        await session.commit()

    assert first["holdings_created"] == 0
    assert first["transactions_imported"] == 1
    assert first["duplicate_transactions_skipped"] == 1

    current_statement[0] = parsed_statement("120")
    async with session_factory() as session:
        second = await upload_router.upload_fidelity_pdf(FakeUpload(), session)
        await session.commit()
        holdings = list((await session.execute(select(Holding))).scalars())
        transactions = list(
            (await session.execute(select(Transaction))).scalars()
        )

    assert second["holdings_created"] == 0
    assert second["transactions_imported"] == 1
    assert second["duplicate_transactions_skipped"] == 1
    assert len(holdings) == 1
    assert holdings[0].snapshot_date == date(2025, 6, 30)
    assert holdings[0].total_quantity == Decimal("5")
    assert len(transactions) == 3
    assert any(transaction.notes == "Manual entry" for transaction in transactions)
    december = next(
        transaction
        for transaction in transactions
        if transaction.date == date(2024, 12, 1)
    )
    assert december.total_native == Decimal("120")

    current_statement[0] = FidelityParseResult(
        participant_number="participant",
        period_start=date(2025, 7, 1),
        period_end=date(2025, 12, 31),
        account_value_usd=Decimal("0"),
        holdings=[],
        transactions=[],
    )
    async with session_factory() as session:
        await upload_router.upload_fidelity_pdf(FakeUpload(), session)
        await session.commit()

    current_statement[0] = parsed_statement("120")
    async with session_factory() as session:
        older = await upload_router.upload_fidelity_pdf(FakeUpload(), session)
        await session.commit()
        holdings = list((await session.execute(select(Holding))).scalars())
        account = (await session.execute(select(Account))).scalar_one()

    assert older["holdings_created"] == 0
    assert holdings == []
    assert account.last_holdings_snapshot_date == date(2025, 12, 31)
    await engine.dispose()
