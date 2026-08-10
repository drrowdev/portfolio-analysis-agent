from __future__ import annotations

import math
import statistics
from decimal import Decimal, ROUND_HALF_UP

from app.schemas.analysis import (
    ConcentrationMetrics,
    PerformanceRiskMetrics,
    SectorExposure,
    TurnoverMetrics,
)
from app.schemas.portfolio import PerformanceResponse


_PCT = Decimal("0.01")
_MONEY = Decimal("0.01")


def _round_optional(value: float | None, digits: int = 2) -> float | None:
    return round(value, digits) if value is not None and math.isfinite(value) else None


def _period_returns(cumulative_pct: list[float]) -> list[float]:
    returns: list[float] = []
    previous_wealth = 1.0
    for cumulative in cumulative_pct:
        wealth = 1.0 + cumulative / 100.0
        if previous_wealth > 0:
            returns.append(wealth / previous_wealth - 1.0)
        previous_wealth = wealth
    return returns[1:]


def _max_drawdown(cumulative_pct: list[float]) -> float | None:
    if not cumulative_pct:
        return None
    peak = 1.0
    worst = 0.0
    for cumulative in cumulative_pct:
        wealth = 1.0 + cumulative / 100.0
        peak = max(peak, wealth)
        if peak > 0:
            worst = min(worst, wealth / peak - 1.0)
    return abs(worst) * 100.0


def calculate_performance_risk(
    response: PerformanceResponse,
) -> PerformanceRiskMetrics:
    portfolio_cumulative = [point.portfolio_return_pct for point in response.data]
    benchmark_cumulative = [point.sp500_return_pct for point in response.data]
    portfolio_returns = _period_returns(portfolio_cumulative)
    benchmark_returns = _period_returns(benchmark_cumulative)
    paired = list(zip(portfolio_returns, benchmark_returns))

    annualized_volatility = None
    benchmark_volatility = None
    tracking_error = None
    beta = None
    if len(paired) >= 2:
        portfolio_daily = [pair[0] for pair in paired]
        benchmark_daily = [pair[1] for pair in paired]
        annualized_volatility = statistics.stdev(portfolio_daily) * math.sqrt(252) * 100
        benchmark_volatility = (
            statistics.stdev(benchmark_daily) * math.sqrt(252) * 100
        )
        active_daily = [
            portfolio_return - benchmark_return
            for portfolio_return, benchmark_return in paired
        ]
        tracking_error = statistics.stdev(active_daily) * math.sqrt(252) * 100
        benchmark_variance = statistics.variance(benchmark_daily)
        if benchmark_variance > 0:
            covariance = statistics.covariance(portfolio_daily, benchmark_daily)
            beta = covariance / benchmark_variance

    portfolio_return = portfolio_cumulative[-1] if portfolio_cumulative else None
    benchmark_return = benchmark_cumulative[-1] if benchmark_cumulative else None
    active_return = (
        portfolio_return - benchmark_return
        if portfolio_return is not None and benchmark_return is not None
        else None
    )
    return PerformanceRiskMetrics(
        period=response.period,
        observations=len(response.data),
        portfolio_return_pct=_round_optional(portfolio_return),
        benchmark_return_pct=_round_optional(benchmark_return),
        active_return_pct=_round_optional(active_return),
        annualized_volatility_pct=_round_optional(annualized_volatility),
        benchmark_annualized_volatility_pct=_round_optional(benchmark_volatility),
        tracking_error_pct=_round_optional(tracking_error),
        beta=_round_optional(beta, 3),
        max_drawdown_pct=_round_optional(_max_drawdown(portfolio_cumulative)),
        benchmark_max_drawdown_pct=_round_optional(
            _max_drawdown(benchmark_cumulative)
        ),
    )


def calculate_concentration(
    position_values: list[tuple[str, Decimal]],
) -> ConcentrationMetrics:
    positive = [(symbol, value) for symbol, value in position_values if value > 0]
    invested = sum((value for _, value in positive), Decimal("0"))
    if invested <= 0:
        return ConcentrationMetrics(
            invested_value_eur=Decimal("0.00"),
            position_count=0,
            largest_position_symbol=None,
            largest_position_pct=None,
            top_five_positions_pct=None,
            herfindahl_index=None,
        )

    weighted = sorted(
        ((symbol, value / invested * 100) for symbol, value in positive),
        key=lambda item: item[1],
        reverse=True,
    )
    hhi = sum(((weight / 100) ** 2 for _, weight in weighted), Decimal("0"))
    return ConcentrationMetrics(
        invested_value_eur=invested.quantize(_MONEY, rounding=ROUND_HALF_UP),
        position_count=len(weighted),
        largest_position_symbol=weighted[0][0],
        largest_position_pct=weighted[0][1].quantize(
            _PCT, rounding=ROUND_HALF_UP
        ),
        top_five_positions_pct=sum(
            (weight for _, weight in weighted[:5]), Decimal("0")
        ).quantize(_PCT, rounding=ROUND_HALF_UP),
        herfindahl_index=hhi.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
    )


def calculate_sector_exposure(
    sector_values: dict[str, Decimal],
    invested_value_eur: Decimal | None = None,
) -> list[SectorExposure]:
    total = (
        invested_value_eur
        if invested_value_eur is not None
        else sum(
            (value for value in sector_values.values() if value > 0),
            Decimal("0"),
        )
    )
    if total <= 0:
        return []
    return [
        SectorExposure(
            sector=sector,
            value_eur=value.quantize(_MONEY, rounding=ROUND_HALF_UP),
            weight_pct=(value / total * 100).quantize(
                _PCT, rounding=ROUND_HALF_UP
            ),
        )
        for sector, value in sorted(
            sector_values.items(), key=lambda item: item[1], reverse=True
        )
        if value > 0
    ]


def calculate_ytd_turnover(
    *,
    year: int,
    traded_notionals_eur: list[Decimal],
    portfolio_value_eur: Decimal,
) -> TurnoverMetrics:
    """Measure gross YTD traded notional against current total portfolio value."""
    traded = sum((abs(value) for value in traded_notionals_eur), Decimal("0"))
    turnover = (
        (traded / portfolio_value_eur * 100).quantize(
            _PCT,
            rounding=ROUND_HALF_UP,
        )
        if portfolio_value_eur > 0
        else None
    )
    return TurnoverMetrics(
        year=year,
        traded_notional_eur=traded.quantize(_MONEY, rounding=ROUND_HALF_UP),
        portfolio_value_eur=portfolio_value_eur.quantize(
            _MONEY,
            rounding=ROUND_HALF_UP,
        ),
        ytd_turnover_pct=turnover,
        methodology=(
            "Gross year-to-date buy and sell notional divided by current total "
            "portfolio value, including cash. It is not annualized."
        ),
    )
