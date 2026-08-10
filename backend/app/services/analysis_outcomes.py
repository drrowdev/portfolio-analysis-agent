"""Forward outcome evaluation for shadow recommendations."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pandas as pd
import yfinance as yf
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.analysis import RecommendationOutcome, ShadowRecommendation
from app.services.symbol_metadata import yahoo_symbol

logger = logging.getLogger(__name__)

OUTCOME_HORIZONS = (1, 5, 20, 60)


def _price_series(ticker: str, start: date, end: date) -> pd.Series:
    frame = yf.download(
        ticker,
        start=start.isoformat(),
        end=end.isoformat(),
        auto_adjust=False,
        progress=False,
    )
    if frame.empty:
        return pd.Series(dtype=float)

    field = "Adj Close" if "Adj Close" in frame.columns else "Close"
    series = frame[field]
    if isinstance(series, pd.DataFrame):
        series = series.iloc[:, 0]
    series = pd.to_numeric(series, errors="coerce").dropna()
    series.index = pd.to_datetime(series.index).tz_localize(None).normalize()
    return series


def _native_to_eur(
    native_prices: pd.Series,
    currency: str,
    start: date,
    end: date,
) -> pd.Series:
    if currency.upper() == "EUR":
        return native_prices

    fx = _price_series(f"EUR{currency.upper()}=X", start, end)
    if fx.empty:
        return pd.Series(dtype=float)

    aligned_fx = fx.reindex(
        native_prices.index,
        method="ffill",
        tolerance=pd.Timedelta(days=4),
    )
    return (native_prices / aligned_fx).dropna()


def _evaluate_history(
    *,
    created_at: datetime,
    decision: str,
    execution_assumption: str,
    amount_eur: float,
    transaction_cost_eur: float,
    tax_impact_eur: float,
    asset_eur: pd.Series,
    benchmark_eur: pd.Series,
) -> list[dict[str, Any]]:
    """Calculate net active returns on benchmark trading sessions."""
    history = pd.concat(
        [
            asset_eur.rename("asset"),
            benchmark_eur.rename("benchmark"),
        ],
        axis=1,
        join="inner",
    ).sort_index()
    history = history.dropna()
    history = history[history.index.date > created_at.date()]
    if history.empty:
        return []

    fill = history.iloc[0]
    fill_date = history.index[0].date()
    cost_drag_pct = (transaction_cost_eur / amount_eur) * 100
    tax_drag_pct = (tax_impact_eur / amount_eur) * 100
    results: list[dict[str, Any]] = []

    for horizon in OUTCOME_HORIZONS:
        if len(history) <= horizon:
            continue
        observed = history.iloc[horizon]
        asset_return = (float(observed["asset"]) / float(fill["asset"]) - 1) * 100
        benchmark_return = (
            float(observed["benchmark"]) / float(fill["benchmark"]) - 1
        ) * 100
        if decision == "buy":
            recommended_return = asset_return
            hold_current_return = (
                0.0 if execution_assumption == "cash" else benchmark_return
            )
        else:
            recommended_return = (
                0.0 if execution_assumption == "cash" else benchmark_return
            )
            hold_current_return = asset_return
        gross_value_add = recommended_return - hold_current_return
        results.append(
            {
                "horizon_days": horizon,
                "fill_date": fill_date.isoformat(),
                "evaluation_date": history.index[horizon].date().isoformat(),
                "asset_return_pct": asset_return,
                "benchmark_return_pct": benchmark_return,
                "recommended_return_pct": recommended_return,
                "hold_current_return_pct": hold_current_return,
                "recommended_active_return_pct": (
                    recommended_return - benchmark_return
                ),
                "gross_value_add_pct": gross_value_add,
                "transaction_cost_drag_pct": cost_drag_pct,
                "tax_drag_pct": tax_drag_pct,
                "net_value_add_pct": (
                    gross_value_add - cost_drag_pct - tax_drag_pct
                ),
                "net_active_return_pct": (
                    recommended_return
                    - benchmark_return
                    - cost_drag_pct
                    - tax_drag_pct
                ),
            }
        )
    return results


def _download_and_evaluate(
    recommendation: ShadowRecommendation,
    benchmark_ticker: str,
    today: date,
) -> list[dict[str, Any]]:
    payload = recommendation.recommendation_json
    symbol = payload.get("symbol")
    currency = payload.get("currency")
    amount_eur = payload.get("amount_eur")
    execution_assumption = payload.get("execution_assumption")
    tax_impact_eur = payload.get("estimated_tax_impact_eur")
    if amount_eur is None:
        quantity = payload.get("quantity")
        reference_price = payload.get("reference_price_eur")
        if quantity is not None and reference_price is not None:
            amount_eur = float(quantity) * float(reference_price)
    if (
        not symbol
        or not currency
        or not amount_eur
        or execution_assumption not in {"cash", "benchmark"}
        or tax_impact_eur is None
    ):
        return []

    start = recommendation.created_at.date() - timedelta(days=7)
    end = today + timedelta(days=1)
    asset_native = _price_series(yahoo_symbol(symbol), start, end)
    benchmark_native = _price_series(benchmark_ticker, start, end)
    asset_eur = _native_to_eur(asset_native, currency, start, end)
    benchmark_eur = _native_to_eur(benchmark_native, "USD", start, end)
    if asset_eur.empty or benchmark_eur.empty:
        return []

    return _evaluate_history(
        created_at=recommendation.created_at,
        decision=recommendation.decision,
        execution_assumption=execution_assumption,
        amount_eur=float(amount_eur),
        transaction_cost_eur=float(
            payload.get("estimated_transaction_cost_eur") or 0
        ),
        tax_impact_eur=float(tax_impact_eur),
        asset_eur=asset_eur,
        benchmark_eur=benchmark_eur,
    )


async def evaluate_due_outcomes(
    db: AsyncSession,
    *,
    today: date | None = None,
) -> int:
    """Persist newly observable horizons for buy and sell decisions."""
    evaluation_date = today or datetime.now(UTC).date()
    result = await db.execute(
        select(ShadowRecommendation)
        .options(
            selectinload(ShadowRecommendation.outcomes),
            selectinload(ShadowRecommendation.run),
        )
        .where(ShadowRecommendation.decision.in_(("buy", "sell")))
        .order_by(ShadowRecommendation.created_at)
    )
    recommendations = list(result.scalars().all())
    recorded = 0
    status_changed = False

    for recommendation in recommendations:
        existing = {
            outcome.horizon_trading_days for outcome in recommendation.outcomes
        }
        if all(horizon in existing for horizon in OUTCOME_HORIZONS):
            continue

        benchmark_ticker = recommendation.run.policy_json.get(
            "benchmark_ticker",
            "^SP500TR",
        )
        try:
            outcomes = await asyncio.to_thread(
                _download_and_evaluate,
                recommendation,
                benchmark_ticker,
                evaluation_date,
            )
        except Exception:
            logger.exception(
                "Unable to evaluate recommendation %s",
                recommendation.id,
            )
            continue
        if (
            outcomes
            and recommendation.valid_until is not None
            and date.fromisoformat(outcomes[0]["fill_date"])
            > recommendation.valid_until.date()
        ):
            recommendation.status = "expired_unfilled"
            status_changed = True
            continue

        expected_alpha = recommendation.recommendation_json.get(
            "expected_net_alpha_pct"
        )
        expected_alpha_horizon = recommendation.recommendation_json.get(
            "expected_alpha_horizon_days"
        )
        recorded_horizons: set[int] = set()
        for outcome in outcomes:
            if outcome["horizon_days"] in existing:
                continue
            net_active_return = outcome["net_active_return_pct"]
            db.add(
                RecommendationOutcome(
                    recommendation_id=recommendation.id,
                    horizon_trading_days=outcome["horizon_days"],
                    evaluated_at=datetime.now(UTC).replace(tzinfo=None),
                    outcome_json={
                        **outcome,
                        "expected_net_alpha_pct": expected_alpha,
                        "met_expected_alpha": (
                            net_active_return >= float(expected_alpha)
                            if expected_alpha is not None
                            and outcome["horizon_days"] == expected_alpha_horizon
                            else None
                        ),
                        "methodology": (
                            "Next common close; explicit cash-or-benchmark execution "
                            "counterfactual; EUR conversion; one-time estimated cost "
                            "and tax drag"
                        ),
                    },
                )
            )
            recorded_horizons.add(outcome["horizon_days"])
            recorded += 1
        if 60 in existing | recorded_horizons:
            recommendation.status = "evaluated"
            status_changed = True

    if recorded or status_changed:
        await db.commit()
    return recorded
