"""Deterministic point-in-time universe backtest for the locked alpha hypothesis."""

from __future__ import annotations

import math
import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from functools import lru_cache
from statistics import mean, stdev
from typing import Any, Literal

import exchange_calendars as xcals
import pandas as pd

from app.services import tax as tax_math
from app.services.backtest_spec import (
    BacktestDataError,
    LockedBacktestInputs,
    MembershipInterval,
    members_on,
)


_INITIAL_VALUE_EUR = 100_000.0
_TRADING_DAYS = 252
_EPSILON = 1e-9
TaxMode = Literal["deferred", "standard"]


@dataclass
class _Lot:
    quantity: float
    unit_basis_eur: float
    acquired_on: date


@dataclass
class _TradeEvent:
    event_date: date
    portfolio_value_eur: float
    gross_notional_eur: float
    transaction_cost_eur: float
    tax_eur: float


def _finite_positive(value: Any) -> bool:
    try:
        return math.isfinite(float(value)) and float(value) > 0
    except (TypeError, ValueError):
        return False


@lru_cache(maxsize=16)
def _xnys_calendar(start_year: int, end_year: int):
    return xcals.get_calendar(
        "XNYS",
        start=f"{start_year - 1}-01-01",
        end=f"{end_year + 1}-12-31",
    )


def _xnys_sessions(start: date, end: date) -> pd.DatetimeIndex:
    calendar = _xnys_calendar(start.year, end.year)
    sessions = calendar.sessions_in_range(
        pd.Timestamp(start),
        pd.Timestamp(end),
    )
    return sessions.tz_localize(None) if sessions.tz is not None else sessions


class _AlignedPrices:
    def __init__(
        self,
        prices: pd.DataFrame,
        benchmark: str,
        maximum_age_days: int,
    ) -> None:
        if benchmark not in prices.columns:
            raise BacktestDataError(f"Market data does not contain {benchmark}.")
        benchmark_levels = prices[benchmark].dropna()
        benchmark_levels = benchmark_levels[benchmark_levels.map(_finite_positive)]
        if benchmark_levels.empty:
            raise BacktestDataError("Benchmark market data is empty.")
        first_observation = pd.Timestamp(benchmark_levels.index.min()).date()
        last_observation = pd.Timestamp(benchmark_levels.index.max()).date()
        self.calendar = _xnys_sessions(first_observation, last_observation)
        self._raw = prices.sort_index()
        self._maximum_age_days = maximum_age_days
        self._cache: dict[str, pd.Series] = {}

    def raw_series(self, ticker: str) -> pd.Series:
        if ticker not in self._raw.columns:
            return pd.Series(dtype=float)
        return self._raw[ticker]

    def series(self, ticker: str) -> pd.Series:
        cached = self._cache.get(ticker)
        if cached is not None:
            return cached
        if ticker not in self._raw.columns:
            aligned = pd.Series(float("nan"), index=self.calendar, dtype=float)
            self._cache[ticker] = aligned
            return aligned
        raw = self._raw[ticker].reindex(self.calendar)
        raw = raw.where(raw.map(lambda value: pd.isna(value) or _finite_positive(value)))
        observed_at = pd.Series(pd.NaT, index=self.calendar, dtype="datetime64[ns]")
        observed_at.loc[raw.notna()] = self.calendar[raw.notna()]
        observed_at = observed_at.ffill()
        aligned = raw.ffill()
        age_days = pd.Series(self.calendar, index=self.calendar) - observed_at
        aligned = aligned.where(
            observed_at.notna()
            & (age_days.dt.days <= self._maximum_age_days)
        )
        self._cache[ticker] = aligned.astype(float)
        return self._cache[ticker]

    def level(self, ticker: str, timestamp: pd.Timestamp) -> float:
        value = self.series(ticker).get(timestamp)
        if not _finite_positive(value):
            raise BacktestDataError(
                f"No age-compliant EUR price for {ticker} on {timestamp.date()}."
            )
        return float(value)


class _VirtualPortfolio:
    def __init__(
        self,
        *,
        prices: _AlignedPrices,
        benchmark: str,
        start_at: pd.Timestamp,
        tax_mode: TaxMode,
        transaction_cost_bps: float,
    ) -> None:
        self.prices = prices
        self.benchmark = benchmark
        self.tax_mode = tax_mode
        self.cost_rate = transaction_cost_bps / 10_000
        benchmark_price = prices.level(benchmark, start_at)
        quantity = _INITIAL_VALUE_EUR / benchmark_price
        self.shares: dict[str, float] = {benchmark: quantity}
        self.lots: dict[str, list[_Lot]] = {
            benchmark: [
                _Lot(
                    quantity=quantity,
                    unit_basis_eur=benchmark_price,
                    acquired_on=start_at.date(),
                )
            ]
        }
        self.cash_eur = 0.0
        self.taxable_income_by_year: dict[int, float] = defaultdict(float)
        self.tax_liability_by_year: dict[int, float] = defaultdict(float)
        self.events: list[_TradeEvent] = []

    def value(self, timestamp: pd.Timestamp) -> float:
        return self.cash_eur + sum(
            quantity * self.prices.level(ticker, timestamp)
            for ticker, quantity in self.shares.items()
            if quantity > _EPSILON
        )

    def weights(self, timestamp: pd.Timestamp) -> dict[str, float]:
        total = self.value(timestamp)
        if total <= 0:
            raise BacktestDataError("The simulated portfolio has no positive value.")
        return {
            ticker: quantity * self.prices.level(ticker, timestamp) / total
            for ticker, quantity in self.shares.items()
            if quantity > _EPSILON
        }

    def max_position_weight(self, timestamp: pd.Timestamp) -> float:
        weights = self.weights(timestamp)
        active_weights = [
            value for ticker, value in weights.items() if ticker != self.benchmark
        ]
        return max(active_weights, default=0.0)

    def _consume_lots(
        self,
        ticker: str,
        quantity: float,
        sell_price: float,
        sell_fee: float,
        sold_on: date,
    ) -> float:
        remaining = quantity
        consumed: list[tax_math.TaxLot] = []
        ticker_lots = self.lots.setdefault(ticker, [])
        while remaining > _EPSILON and ticker_lots:
            lot = ticker_lots[0]
            take = min(remaining, lot.quantity)
            consumed.append(
                tax_math.TaxLot(
                    quantity=Decimal(str(take)),
                    cost_per_share_eur=Decimal(str(lot.unit_basis_eur)),
                    over_10_years=tax_math.held_at_least_10_years(
                        lot.acquired_on,
                        sold_on,
                    ),
                )
            )
            lot.quantity -= take
            remaining -= take
            if lot.quantity <= _EPSILON:
                ticker_lots.pop(0)
        if remaining > 1e-6:
            raise BacktestDataError(
                f"Virtual FIFO lots do not cover the {ticker} sale."
            )
        if self.tax_mode == "deferred":
            return 0.0
        result = tax_math.compute(
            consumed,
            Decimal(str(sell_price)),
            Decimal(str(sell_fee)),
            Decimal(str(quantity)),
        )
        if result.shortfall_qty > 0:
            raise BacktestDataError(
                f"Virtual FIFO lots do not cover the {ticker} sale."
            )
        year = sold_on.year
        previous_income = self.taxable_income_by_year[year]
        previous_liability = self.tax_liability_by_year[year]
        new_income = previous_income + float(result.optimum_gain_eur)
        new_liability = float(
            tax_math.bracket_total_tax(Decimal(str(new_income)))
        )
        self.taxable_income_by_year[year] = new_income
        self.tax_liability_by_year[year] = new_liability
        return new_liability - previous_liability

    def trade_to_targets(
        self,
        timestamp: pd.Timestamp,
        target_weights: dict[str, float],
    ) -> None:
        if not target_weights:
            target_weights = {self.benchmark: 1.0}
        target_total = sum(target_weights.values())
        if abs(target_total - 1.0) > 1e-8 or any(
            weight < 0 for weight in target_weights.values()
        ):
            raise BacktestDataError("Target weights must be non-negative and sum to 1.")

        pretrade_value = self.value(timestamp)
        desired_values = {
            ticker: pretrade_value * weight
            for ticker, weight in target_weights.items()
        }
        gross_notional = 0.0
        transaction_cost = 0.0
        tax_change = 0.0

        for ticker in sorted(set(self.shares) | set(target_weights)):
            current_quantity = self.shares.get(ticker, 0.0)
            if current_quantity <= _EPSILON:
                continue
            price = self.prices.level(ticker, timestamp)
            current_value = current_quantity * price
            desired_value = desired_values.get(ticker, 0.0)
            if current_value <= desired_value + 1e-7:
                continue
            sell_value = current_value - desired_value
            sell_quantity = min(current_quantity, sell_value / price)
            fee = sell_value * self.cost_rate
            tax = self._consume_lots(
                ticker,
                sell_quantity,
                price,
                fee,
                timestamp.date(),
            )
            self.shares[ticker] = current_quantity - sell_quantity
            if self.shares[ticker] <= _EPSILON:
                self.shares.pop(ticker, None)
            self.cash_eur += sell_value - fee - tax
            gross_notional += sell_value
            transaction_cost += fee
            tax_change += tax

        deficits: dict[str, float] = {}
        for ticker, desired_value in desired_values.items():
            price = self.prices.level(ticker, timestamp)
            current_value = self.shares.get(ticker, 0.0) * price
            if desired_value > current_value + 1e-7:
                deficits[ticker] = desired_value - current_value
        required_cash = sum(
            deficit * (1 + self.cost_rate) for deficit in deficits.values()
        )
        scale = (
            min(1.0, max(0.0, self.cash_eur) / required_cash)
            if required_cash > 0
            else 0.0
        )
        for ticker in sorted(deficits):
            notional = deficits[ticker] * scale
            if notional <= _EPSILON:
                continue
            price = self.prices.level(ticker, timestamp)
            fee = notional * self.cost_rate
            quantity = notional / price
            self.cash_eur -= notional + fee
            self.shares[ticker] = self.shares.get(ticker, 0.0) + quantity
            self.lots.setdefault(ticker, []).append(
                _Lot(
                    quantity=quantity,
                    unit_basis_eur=(notional + fee) / quantity,
                    acquired_on=timestamp.date(),
                )
            )
            gross_notional += notional
            transaction_cost += fee
        if abs(self.cash_eur) < 1e-7:
            self.cash_eur = 0.0
        self.events.append(
            _TradeEvent(
                event_date=timestamp.date(),
                portfolio_value_eur=pretrade_value,
                gross_notional_eur=gross_notional,
                transaction_cost_eur=transaction_cost,
                tax_eur=tax_change,
            )
        )


def _signal_snapshot(
    prices: _AlignedPrices,
    *,
    signal_at: pd.Timestamp,
    candidates: set[str],
    benchmark: str,
    specification: dict[str, Any],
) -> dict[str, float]:
    signal = specification["signal"]
    lookback = int(signal["momentum_lookback_trading_days"])
    skip = int(signal["momentum_skip_recent_trading_days"])
    trend_days = int(signal["trend_sma_trading_days"])
    calendar = prices.calendar[prices.calendar <= signal_at]
    required = max(lookback + 1, trend_days)
    if len(calendar) < required:
        return {}

    benchmark_series = prices.series(benchmark).reindex(calendar)
    benchmark_end = benchmark_series.iloc[-(skip + 1)]
    benchmark_start = benchmark_series.iloc[-(lookback + 1)]
    if not _finite_positive(benchmark_end) or not _finite_positive(benchmark_start):
        return {}
    benchmark_momentum = float(benchmark_end / benchmark_start - 1)

    scores: dict[str, float] = {}
    for ticker in sorted(candidates):
        series = prices.series(ticker).reindex(calendar)
        current = series.iloc[-1]
        momentum_end = series.iloc[-(skip + 1)]
        momentum_start = series.iloc[-(lookback + 1)]
        trend_window = series.iloc[-trend_days:]
        if (
            not _finite_positive(current)
            or not _finite_positive(momentum_end)
            or not _finite_positive(momentum_start)
            or trend_window.isna().any()
        ):
            continue
        absolute_momentum = float(momentum_end / momentum_start - 1)
        relative_momentum = absolute_momentum - benchmark_momentum
        trend_sma = float(trend_window.mean())
        if (
            (
                signal["require_positive_absolute_momentum"]
                and absolute_momentum <= 0
            )
            or (
                signal["require_positive_benchmark_relative_momentum"]
                and relative_momentum <= 0
            )
            or (signal["require_price_above_trend_sma"] and current <= trend_sma)
        ):
            continue
        scores[ticker] = relative_momentum
    return scores


def _month_end_signals(calendar: pd.DatetimeIndex) -> list[pd.Timestamp]:
    if calendar.empty:
        return []
    frame = pd.Series(calendar, index=calendar)
    return list(frame.groupby(calendar.to_period("M")).max())


def _validate_membership_price_coverage(
    prices: pd.DataFrame,
    intervals: tuple[MembershipInterval, ...],
    start: date,
    end: date,
    *,
    benchmark: str,
    maximum_age_days: int,
    minimum_coverage_pct: float,
) -> list[dict[str, Any]]:
    aligned = _AlignedPrices(prices, benchmark, maximum_age_days)
    failures: list[dict[str, Any]] = []
    for interval in intervals:
        overlap_start = max(start, interval.start_date)
        overlap_end = min(end, interval.end_date or end)
        if overlap_end < overlap_start:
            continue
        expected_dates = aligned.calendar[
            (aligned.calendar >= pd.Timestamp(overlap_start))
            & (aligned.calendar <= pd.Timestamp(overlap_end))
        ]
        if expected_dates.empty:
            continue
        series = aligned.series(interval.ticker).reindex(expected_dates)
        covered = int(series.map(_finite_positive).sum())
        coverage_pct = covered / len(expected_dates) * 100
        if coverage_pct + 1e-9 < minimum_coverage_pct:
            failures.append(
                {
                    "ticker": interval.ticker,
                    "membership_start": overlap_start.isoformat(),
                    "membership_end": overlap_end.isoformat(),
                    "expected_sessions": len(expected_dates),
                    "covered_sessions": covered,
                    "coverage_pct": coverage_pct,
                }
            )
    return failures


def _moving_block_interval(
    monthly_active_returns: list[float],
    specification: dict[str, Any],
) -> tuple[float | None, float | None]:
    statistics = specification["statistics"]
    sample_count = int(statistics["bootstrap_samples"])
    block_size = int(statistics["bootstrap_block_months"])
    confidence = float(statistics["confidence_level_pct"]) / 100
    if len(monthly_active_returns) < max(12, block_size):
        return None, None
    rng = random.Random(int(statistics["bootstrap_seed"]))
    values = monthly_active_returns
    starts = list(range(len(values) - block_size + 1))
    samples: list[float] = []
    for _ in range(sample_count):
        sampled: list[float] = []
        while len(sampled) < len(values):
            start = rng.choice(starts)
            sampled.extend(values[start:start + block_size])
        samples.append(mean(sampled[:len(values)]) * 12)
    samples.sort()
    tail = (1 - confidence) / 2
    lower_index = max(0, min(len(samples) - 1, int(tail * len(samples))))
    upper_index = max(
        0,
        min(len(samples) - 1, int((1 - tail) * len(samples)) - 1),
    )
    return samples[lower_index], samples[upper_index]


def _max_drawdown(returns: list[float]) -> float | None:
    if not returns:
        return None
    wealth = 1.0
    peak = 1.0
    worst = 0.0
    for value in returns:
        wealth *= 1 + value
        peak = max(peak, wealth)
        worst = min(worst, wealth / peak - 1)
    return worst


def _split_metrics(
    daily: pd.DataFrame,
    events: list[_TradeEvent],
    *,
    split_name: str,
    start: date,
    end: date,
    specification: dict[str, Any],
) -> dict[str, Any]:
    subset = daily.loc[pd.Timestamp(start):pd.Timestamp(end)].copy()
    if subset.empty:
        return {
            "period": split_name,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "observations": 0,
        }
    strategy_returns = subset["strategy_return"].dropna().tolist()
    benchmark_returns = subset["benchmark_return"].dropna().tolist()
    if not strategy_returns or len(strategy_returns) != len(benchmark_returns):
        raise BacktestDataError(f"{split_name} has incomplete return observations.")
    strategy_growth = math.prod(1 + value for value in strategy_returns)
    benchmark_growth = math.prod(1 + value for value in benchmark_returns)
    elapsed_years = max(
        (subset.index[-1].date() - subset.index[0].date()).days / 365.2425,
        1 / 365.2425,
    )
    strategy_cagr = strategy_growth ** (1 / elapsed_years) - 1
    benchmark_cagr = benchmark_growth ** (1 / elapsed_years) - 1
    active_cagr = (
        (strategy_growth / benchmark_growth) ** (1 / elapsed_years) - 1
        if benchmark_growth > 0
        else None
    )
    active_daily = [
        strategy - benchmark
        for strategy, benchmark in zip(strategy_returns, benchmark_returns)
    ]
    strategy_vol = (
        stdev(strategy_returns) * math.sqrt(_TRADING_DAYS)
        if len(strategy_returns) > 1
        else None
    )
    tracking_error = (
        stdev(active_daily) * math.sqrt(_TRADING_DAYS)
        if len(active_daily) > 1
        else None
    )
    information_ratio = (
        mean(active_daily) * _TRADING_DAYS / tracking_error
        if tracking_error and tracking_error > 0
        else None
    )
    monthly = subset[["strategy_return", "benchmark_return"]].copy()
    monthly = (1 + monthly).resample("ME").prod() - 1
    monthly_active = (
        monthly["strategy_return"] - monthly["benchmark_return"]
    ).dropna().tolist()
    ci_lower, ci_upper = _moving_block_interval(
        monthly_active,
        specification,
    )
    split_events = [
        event for event in events if start <= event.event_date <= end
    ]
    annual_turnover = (
        sum(
            event.gross_notional_eur / event.portfolio_value_eur
            for event in split_events
            if event.portfolio_value_eur > 0
        )
        / elapsed_years
    )
    return {
        "period": split_name,
        "start_date": subset.index[0].date().isoformat(),
        "end_date": subset.index[-1].date().isoformat(),
        "observations": len(subset),
        "months": len(monthly),
        "strategy_cumulative_return_pct": (strategy_growth - 1) * 100,
        "benchmark_cumulative_return_pct": (benchmark_growth - 1) * 100,
        "net_active_cumulative_return_pct": (
            strategy_growth / benchmark_growth - 1
        ) * 100,
        "strategy_cagr_pct": strategy_cagr * 100,
        "benchmark_cagr_pct": benchmark_cagr * 100,
        "net_active_cagr_pct": (
            active_cagr * 100 if active_cagr is not None else None
        ),
        "annualized_volatility_pct": (
            strategy_vol * 100 if strategy_vol is not None else None
        ),
        "tracking_error_pct": (
            tracking_error * 100 if tracking_error is not None else None
        ),
        "information_ratio": information_ratio,
        "max_drawdown_pct": (
            _max_drawdown(strategy_returns) * 100
            if strategy_returns
            else None
        ),
        "annualized_gross_turnover_pct": annual_turnover * 100,
        "active_return_ci_lower_pct": (
            ci_lower * 100 if ci_lower is not None else None
        ),
        "active_return_ci_upper_pct": (
            ci_upper * 100 if ci_upper is not None else None
        ),
        "transaction_cost_eur": sum(
            event.transaction_cost_eur for event in split_events
        ),
        "tax_eur": sum(event.tax_eur for event in split_events),
    }


def _period_bounds(specification: dict[str, Any]) -> dict[str, tuple[date, date]]:
    return {
        name: (
            date.fromisoformat(values["start"]),
            date.fromisoformat(values["end"]),
        )
        for name, values in specification["periods"].items()
        if name != "warmup"
    }


def _registered_period_coverage_failures(
    prices: pd.DataFrame,
    specification: dict[str, Any],
    *,
    benchmark: str,
    maximum_age_days: int,
) -> list[dict[str, Any]]:
    aligned = _AlignedPrices(prices, benchmark, maximum_age_days)
    failures: list[dict[str, Any]] = []
    raw_benchmark = aligned.raw_series(benchmark)
    for period, values in specification["periods"].items():
        start = date.fromisoformat(values["start"])
        end = date.fromisoformat(values["end"])
        expected = _xnys_sessions(start, end)
        observed = raw_benchmark.reindex(expected)
        covered = observed.map(_finite_positive)
        missing = expected[~covered]
        if len(missing):
            failures.append(
                {
                    "period": period,
                    "registered_start": start.isoformat(),
                    "registered_end": end.isoformat(),
                    "expected_sessions": len(expected),
                    "covered_sessions": int(covered.sum()),
                    "missing_session_count": len(missing),
                    "missing_session_preview": [
                        value.date().isoformat() for value in missing[:10]
                    ],
                }
            )
    return failures


def _simulate_universe(
    *,
    prices: pd.DataFrame,
    locked: LockedBacktestInputs,
    transaction_cost_bps: float,
    tax_mode: TaxMode,
) -> tuple[pd.DataFrame, list[_TradeEvent], float, int]:
    specification = locked.specification
    benchmark = specification["benchmark"]["ticker"]
    maximum_age = int(specification["execution"]["maximum_price_age_calendar_days"])
    aligned = _AlignedPrices(prices, benchmark, maximum_age)
    period_bounds = _period_bounds(specification)
    simulation_start = min(start for start, _ in period_bounds.values())
    simulation_end = max(end for _, end in period_bounds.values())
    calendar = aligned.calendar[
        (aligned.calendar >= pd.Timestamp(simulation_start))
        & (aligned.calendar <= pd.Timestamp(simulation_end))
    ]
    if len(calendar) < 2:
        raise BacktestDataError("Market data does not cover the registered periods.")

    schedule_calendar = aligned.calendar[
        aligned.calendar <= pd.Timestamp(simulation_end)
    ]
    executions: dict[pd.Timestamp, dict[str, float]] = {}
    selected_count = 0
    all_calendar = list(aligned.calendar)
    calendar_positions = {
        timestamp: index for index, timestamp in enumerate(all_calendar)
    }
    universe_settings = specification["universe_track"]
    active_sleeve = float(universe_settings["active_sleeve_pct"]) / 100
    maximum_names = int(universe_settings["maximum_selected_names"])
    for signal_at in _month_end_signals(schedule_calendar):
        signal_index = calendar_positions[signal_at]
        if signal_index + 1 >= len(all_calendar):
            continue
        execute_at = all_calendar[signal_index + 1]
        if execute_at < calendar[0] or execute_at > calendar[-1]:
            continue
        signal_members = members_on(
            locked.membership_intervals,
            signal_at.date(),
        )
        scores = _signal_snapshot(
            aligned,
            signal_at=signal_at,
            candidates=signal_members,
            benchmark=benchmark,
            specification=specification,
        )
        selected = [
            ticker
            for ticker, _ in sorted(
                scores.items(),
                key=lambda item: (-item[1], item[0]),
            )
            if ticker in members_on(
                locked.membership_intervals,
                execute_at.date(),
            )
        ][:maximum_names]
        selected_count += len(selected)
        if not selected:
            executions[execute_at] = {benchmark: 1.0}
            continue
        active_weight = active_sleeve / len(selected)
        executions[execute_at] = {
            benchmark: 1 - active_sleeve,
            **{ticker: active_weight for ticker in selected},
        }

    portfolio = _VirtualPortfolio(
        prices=aligned,
        benchmark=benchmark,
        start_at=calendar[0],
        tax_mode=tax_mode,
        transaction_cost_bps=transaction_cost_bps,
    )
    previous_value = portfolio.value(calendar[0])
    previous_benchmark = aligned.level(benchmark, calendar[0])
    rows = [
        {
            "date": calendar[0],
            "strategy_return": 0.0,
            "benchmark_return": 0.0,
            "portfolio_value": previous_value,
            "max_active_position_weight": 0.0,
        }
    ]
    for timestamp in calendar[1:]:
        current_benchmark = aligned.level(benchmark, timestamp)
        if timestamp in executions:
            portfolio.trade_to_targets(timestamp, executions[timestamp])
        else:
            current_members = members_on(
                locked.membership_intervals,
                timestamp.date(),
            )
            current_weights = portfolio.weights(timestamp)
            removed = [
                ticker
                for ticker in current_weights
                if ticker != benchmark and ticker not in current_members
            ]
            if removed:
                removed_weight = sum(current_weights.pop(ticker) for ticker in removed)
                current_weights[benchmark] = (
                    current_weights.get(benchmark, 0.0) + removed_weight
                )
                portfolio.trade_to_targets(timestamp, current_weights)
        current_value = portfolio.value(timestamp)
        rows.append(
            {
                "date": timestamp,
                "strategy_return": current_value / previous_value - 1,
                "benchmark_return": current_benchmark / previous_benchmark - 1,
                "portfolio_value": current_value,
                "max_active_position_weight": (
                    portfolio.max_position_weight(timestamp)
                ),
            }
        )
        previous_value = current_value
        previous_benchmark = current_benchmark
    daily = pd.DataFrame(rows).set_index("date")
    return (
        daily,
        portfolio.events,
        float(daily["max_active_position_weight"].max()),
        selected_count,
    )


def _promotion_gate(
    standard_splits: list[dict[str, Any]],
    *,
    maximum_position_pct: float,
    policy: Any,
    specification: dict[str, Any],
) -> tuple[bool, list[str]]:
    holdout = next(
        (split for split in standard_splits if split["period"] == "holdout"),
        None,
    )
    blockers = [
        "Point-in-time historical sector data is unavailable, so the configured "
        "sector cap cannot be verified.",
        "Forward shadow confirmation has not completed.",
    ]
    if not holdout or holdout.get("observations", 0) == 0:
        blockers.append("The sealed holdout has no observations.")
        return False, blockers
    if holdout.get("months", 0) < int(
        specification["statistics"]["minimum_holdout_months"]
    ):
        blockers.append("The sealed holdout is shorter than the registered minimum.")

    checks = (
        (
            holdout.get("net_active_cagr_pct"),
            getattr(policy, "minimum_expected_net_alpha_pct", None),
            lambda value, limit: value > float(limit),
            "Holdout net active CAGR does not exceed the policy minimum.",
        ),
        (
            holdout.get("active_return_ci_lower_pct"),
            0,
            lambda value, limit: value > limit,
            "The holdout active-return confidence interval includes zero.",
        ),
        (
            holdout.get("information_ratio"),
            specification["promotion_gate"]["minimum_information_ratio"],
            lambda value, limit: value >= float(limit),
            "The holdout information ratio is below the registered minimum.",
        ),
        (
            abs(holdout.get("max_drawdown_pct") or 0),
            getattr(policy, "max_drawdown_pct", None),
            lambda value, limit: value <= float(limit),
            "The holdout drawdown exceeds the policy limit.",
        ),
        (
            holdout.get("annualized_volatility_pct"),
            getattr(policy, "max_annualized_volatility_pct", None),
            lambda value, limit: value <= float(limit),
            "The holdout volatility exceeds the policy limit.",
        ),
        (
            holdout.get("tracking_error_pct"),
            getattr(policy, "max_tracking_error_pct", None),
            lambda value, limit: value <= float(limit),
            "The holdout tracking error exceeds the policy limit.",
        ),
        (
            holdout.get("annualized_gross_turnover_pct"),
            getattr(policy, "max_annual_turnover_pct", None),
            lambda value, limit: value <= float(limit),
            "The holdout turnover exceeds the policy limit.",
        ),
        (
            maximum_position_pct,
            getattr(policy, "max_single_position_pct", None),
            lambda value, limit: value <= float(limit),
            "The strategy exceeds the policy single-position limit.",
        ),
    )
    for value, limit, predicate, message in checks:
        if value is None or limit is None:
            blockers.append(message.replace(" exceeds", " cannot be compared with"))
        elif not predicate(float(value), limit):
            blockers.append(message)
    return not blockers, blockers


def run_point_in_time_universe_backtest(
    *,
    prices_eur: pd.DataFrame,
    price_data_hash: str,
    price_data_source: str,
    locked: LockedBacktestInputs,
    policy: Any,
) -> dict[str, Any]:
    """Run both deferred and Finnish-standard-tax scenarios without tuning."""
    specification = locked.specification
    periods = _period_bounds(specification)
    registered_periods = {
        name: (
            date.fromisoformat(values["start"]),
            date.fromisoformat(values["end"]),
        )
        for name, values in specification["periods"].items()
    }
    start = min(value[0] for value in registered_periods.values())
    end = max(value[1] for value in registered_periods.values())
    benchmark = specification["benchmark"]["ticker"]
    maximum_age = int(
        specification["execution"]["maximum_price_age_calendar_days"]
    )
    period_coverage_failures = _registered_period_coverage_failures(
        prices_eur,
        specification,
        benchmark=benchmark,
        maximum_age_days=maximum_age,
    )
    if period_coverage_failures:
        missing_periods = ", ".join(
            failure["period"] for failure in period_coverage_failures
        )
        return {
            "status": "blocked",
            "track": "sp500_universe",
            "spec_version": specification["spec_version"],
            "specification_hash": locked.specification_hash,
            "blockers": [
                "Benchmark prices do not cover every registered period boundary: "
                f"{missing_periods}."
            ],
            "data_manifest": {
                "price_data_source": price_data_source,
                "price_data_hash": price_data_hash,
                "membership_hash": locked.membership_hash,
                "period_coverage_failures": period_coverage_failures,
            },
            "historical_evidence_is_proof_of_future_alpha": False,
        }
    minimum_coverage = float(
        specification["universe_track"]["minimum_constituent_coverage_pct"]
    )
    coverage_failures = _validate_membership_price_coverage(
        prices_eur,
        locked.membership_intervals,
        start,
        end,
        benchmark=benchmark,
        maximum_age_days=maximum_age,
        minimum_coverage_pct=minimum_coverage,
    )
    if coverage_failures:
        missing_prices = sorted(
            {failure["ticker"] for failure in coverage_failures}
        )
        preview = ", ".join(missing_prices[:20])
        suffix = (
            f" and {len(missing_prices) - 20} more"
            if len(missing_prices) > 20
            else ""
        )
        return {
            "status": "blocked",
            "track": "sp500_universe",
            "spec_version": specification["spec_version"],
            "specification_hash": locked.specification_hash,
            "blockers": [
                "Point-in-time member prices are missing for "
                f"{preview}{suffix}. A delisted-security source is required."
            ],
            "data_manifest": {
                "price_data_source": price_data_source,
                "price_data_hash": price_data_hash,
                "membership_hash": locked.membership_hash,
                "missing_members": missing_prices,
                "coverage_failures": coverage_failures,
            },
            "historical_evidence_is_proof_of_future_alpha": False,
        }
    transaction_cost = getattr(policy, "estimated_transaction_cost_bps", None)
    if transaction_cost is None:
        return {
            "status": "blocked",
            "track": "sp500_universe",
            "spec_version": specification["spec_version"],
            "specification_hash": locked.specification_hash,
            "blockers": ["The transaction-cost policy is not configured."],
            "data_manifest": {
                "price_data_source": price_data_source,
                "price_data_hash": price_data_hash,
                "membership_hash": locked.membership_hash,
            },
            "historical_evidence_is_proof_of_future_alpha": False,
        }

    dividend_tax_blocker = (
        "The standard taxable scenario is blocked because adjusted-close returns "
        "include dividends but the registered market-data contract has no "
        "point-in-time dividend distributions for Finnish dividend taxation."
    )
    scenarios: dict[str, Any] = {
        "standard": {
            "tax_mode": "standard",
            "status": "blocked",
            "splits": [],
            "blockers": [dividend_tax_blocker],
        }
    }
    standard_splits: list[dict[str, Any]] = []
    maximum_position_pct = 0.0
    selected_count = 0
    for tax_mode in ("deferred",):
        daily, events, max_position, scenario_selected = _simulate_universe(
            prices=prices_eur,
            locked=locked,
            transaction_cost_bps=float(transaction_cost),
            tax_mode=tax_mode,
        )
        splits = [
            _split_metrics(
                daily,
                events,
                split_name=name,
                start=bounds[0],
                end=bounds[1],
                specification=specification,
            )
            for name, bounds in periods.items()
        ]
        scenarios[tax_mode] = {
            "tax_mode": tax_mode,
            "status": "completed",
            "splits": splits,
            "ending_value_eur": float(daily["portfolio_value"].iloc[-1]),
        }
        maximum_position_pct = max_position * 100
        selected_count = scenario_selected
    promotion_eligible, promotion_blockers = _promotion_gate(
        standard_splits,
        maximum_position_pct=maximum_position_pct,
        policy=policy,
        specification=specification,
    )
    promotion_blockers.append(dividend_tax_blocker)
    promotion_eligible = False
    return {
        "status": "completed_with_exclusions",
        "track": "sp500_universe",
        "spec_version": specification["spec_version"],
        "specification_hash": locked.specification_hash,
        "data_manifest": {
            "price_data_source": price_data_source,
            "price_data_hash": price_data_hash,
            "membership_hash": locked.membership_hash,
            "membership_source_commit": locked.membership_provenance["source_commit"],
            "market_data_rows": int(prices_eur.count().sum()),
        },
        "scenarios": scenarios,
        "maximum_active_position_pct": maximum_position_pct,
        "selected_security_observations": selected_count,
        "promotion_eligible": promotion_eligible,
        "promotion_blockers": promotion_blockers,
        "historical_evidence_is_proof_of_future_alpha": False,
    }
