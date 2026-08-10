from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, time
from statistics import mean, median
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.analysis import AnalysisRun, RecommendationOutcome, ShadowRecommendation
from app.schemas.analysis import (
    AnalysisResult,
    AnalysisSnapshot,
    HorizonEvidence,
    ProofOfValueReport,
    ProofOfValuePolicyState,
    ShadowRunSummary,
)


def analysis_input_hash(input_json: dict[str, Any]) -> str:
    """Hash a JSON-safe record of every deterministic and model input."""
    canonical = json.dumps(
        input_json,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


async def record_completed_run(
    db: AsyncSession,
    *,
    analysis_type: str,
    policy: ProofOfValuePolicyState,
    result: AnalysisResult,
    snapshot: AnalysisSnapshot | None,
    input_json: dict[str, Any] | None = None,
) -> AnalysisRun:
    """Persist an immutable input/output record for a shadow analysis run."""
    input_hash = analysis_input_hash(input_json) if input_json is not None else None
    if result.meta.input_hash != input_hash:
        raise ValueError("Analysis result input hash does not match the persisted input.")
    run = AnalysisRun(
        analysis_type=analysis_type,
        mode=result.meta.mode,
        status="completed",
        model_name=result.meta.model,
        prompt_version=result.meta.prompt_version,
        snapshot_hash=result.meta.snapshot_hash,
        input_hash=input_hash,
        policy_json=policy.model_dump(mode="json"),
        data_quality_json=(
            snapshot.data_quality.model_dump(mode="json")
            if snapshot is not None
            else {
                "can_recommend_trades": result.meta.can_recommend_trades,
                "issues": result.meta.data_quality_issues,
            }
        ),
        snapshot_json=(
            snapshot.model_dump(mode="json") if snapshot is not None else None
        ),
        input_json=input_json,
        result_json=result.model_dump(mode="json"),
    )
    db.add(run)
    await db.flush()

    for recommendation in result.recommendations:
        valid_until = (
            datetime.combine(recommendation.valid_until, time.min)
            if recommendation.valid_until is not None
            else None
        )
        db.add(
            ShadowRecommendation(
                run_id=run.id,
                decision=recommendation.decision,
                symbol=recommendation.symbol,
                status=(
                    "pending_outcome"
                    if recommendation.decision in {"buy", "sell"}
                    else "closed_no_trade"
                ),
                valid_until=valid_until,
                recommendation_json=recommendation.model_dump(mode="json"),
            )
        )
    await db.flush()
    await db.refresh(run)
    return run


async def list_recent_runs(
    db: AsyncSession, limit: int = 20
) -> list[ShadowRunSummary]:
    stmt = (
        select(AnalysisRun)
        .options(selectinload(AnalysisRun.recommendations))
        .order_by(AnalysisRun.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return [
        ShadowRunSummary(
            id=str(run.id),
            analysis_type=run.analysis_type,
            status=run.status,
            mode=run.mode,
            model_name=run.model_name,
            prompt_version=run.prompt_version,
            snapshot_hash=run.snapshot_hash,
            input_hash=run.input_hash,
            recommendation_count=len(run.recommendations),
            created_at=run.created_at,
        )
        for run in result.scalars().all()
    ]


def result_from_dict(data: dict[str, Any]) -> AnalysisResult:
    """Validate data loaded from JSON before it is treated as an analysis result."""
    return AnalysisResult.model_validate(data)


async def proof_of_value_report(db: AsyncSession) -> ProofOfValueReport:
    """Summarize collected evidence without claiming alpha prematurely."""
    total_runs = (
        await db.execute(select(func.count()).select_from(AnalysisRun))
    ).scalar_one()
    reproducible_runs = (
        await db.execute(
            select(func.count())
            .select_from(AnalysisRun)
            .where(
                AnalysisRun.input_hash.is_not(None),
                AnalysisRun.input_json.is_not(None),
            )
        )
    ).scalar_one()
    total_recommendations = (
        await db.execute(select(func.count()).select_from(ShadowRecommendation))
    ).scalar_one()
    evaluated_outcomes = (
        await db.execute(select(func.count()).select_from(RecommendationOutcome))
    ).scalar_one()
    outcome_rows = (
        await db.execute(
            select(
                RecommendationOutcome.recommendation_id,
                RecommendationOutcome.horizon_trading_days,
                RecommendationOutcome.outcome_json,
                ShadowRecommendation.decision,
                ShadowRecommendation.symbol,
                ShadowRecommendation.recommendation_json,
            )
            .join(
                ShadowRecommendation,
                RecommendationOutcome.recommendation_id
                == ShadowRecommendation.id,
            )
        )
    ).all()
    decision_rows = (
        await db.execute(
            select(ShadowRecommendation.decision, func.count())
            .group_by(ShadowRecommendation.decision)
            .order_by(ShadowRecommendation.decision)
        )
    ).all()
    first_run_at, last_run_at = (
        await db.execute(
            select(func.min(AnalysisRun.created_at), func.max(AnalysisRun.created_at))
        )
    ).one()
    review_run_dates = list(
        (
            await db.execute(
                select(AnalysisRun.created_at)
                .where(
                    AnalysisRun.analysis_type == "rebalance",
                    AnalysisRun.status == "completed",
                )
                .order_by(AnalysisRun.created_at)
            )
        ).scalars()
    )

    horizon_groups: dict[tuple[str, int], list[dict[str, Any]]] = {}
    alpha_horizon_cohorts: dict[int, set[tuple[object, ...]]] = {}
    evaluated_recommendation_ids: set[object] = set()
    for (
        recommendation_id,
        horizon,
        outcome,
        decision,
        symbol,
        recommendation,
    ) in outcome_rows:
        if (
            outcome.get("net_value_add_pct") is None
            or outcome.get("net_active_return_pct") is None
        ):
            continue
        evaluated_recommendation_ids.add(recommendation_id)
        candidate_objective = recommendation.get("candidate_objective") or "legacy"
        horizon_groups.setdefault((candidate_objective, horizon), []).append(outcome)
        cohort = (
            outcome.get("fill_date"),
            decision,
            symbol,
            recommendation.get("account_id"),
            recommendation.get("execution_assumption"),
        )
        if recommendation.get("candidate_objective") == "return_seeking":
            alpha_horizon_cohorts.setdefault(horizon, set()).add(cohort)

    horizon_evidence: list[HorizonEvidence] = []
    for (candidate_objective, horizon), outcomes in sorted(
        horizon_groups.items(),
        key=lambda item: (item[0][1], item[0][0]),
    ):
        value_add_returns = [
            float(outcome["net_value_add_pct"]) for outcome in outcomes
        ]
        active_returns = [
            float(outcome["net_active_return_pct"]) for outcome in outcomes
        ]
        expected_results = [
            bool(outcome["met_expected_alpha"])
            for outcome in outcomes
            if outcome.get("met_expected_alpha") is not None
        ]
        horizon_evidence.append(
            HorizonEvidence(
                candidate_objective=candidate_objective,
                horizon_trading_days=horizon,
                evaluated_recommendations=len(outcomes),
                average_net_value_add_pct=round(mean(value_add_returns), 4),
                median_net_value_add_pct=round(median(value_add_returns), 4),
                positive_value_add_rate_pct=round(
                    sum(value > 0 for value in value_add_returns)
                    / len(value_add_returns)
                    * 100,
                    2,
                ),
                average_net_active_return_pct=round(mean(active_returns), 4),
                median_net_active_return_pct=round(median(active_returns), 4),
                positive_active_return_rate_pct=round(
                    sum(value > 0 for value in active_returns)
                    / len(active_returns)
                    * 100,
                    2,
                ),
                expected_alpha_met_rate_pct=(
                    round(
                        sum(expected_results) / len(expected_results) * 100,
                        2,
                    )
                    if expected_results
                    else None
                ),
            )
        )

    now = datetime.now(UTC).replace(tzinfo=None)
    if not review_run_dates:
        operational_gate = "not_started"
    else:
        review_dates = sorted(review_run_dates)
        review_span_days = (review_dates[-1] - review_dates[0]).days
        review_weeks = {
            (value.isocalendar().year, value.isocalendar().week)
            for value in review_dates
        }
        max_gap_days = max(
            (
                (current - previous).days
                for previous, current in zip(review_dates, review_dates[1:])
            ),
            default=0,
        )
        cadence_is_current = (now - review_dates[-1]).days <= 10
        if (
            review_span_days >= 56
            and len(review_weeks) >= 8
            and max_gap_days <= 10
            and cadence_is_current
        ):
            operational_gate = "ready_for_review"
        else:
            operational_gate = "collecting"

    twenty_day_candidate_cohorts = len(alpha_horizon_cohorts.get(20, set()))
    if twenty_day_candidate_cohorts == 0:
        investment_evidence = "insufficient"
        evidence_message = (
            "No validated return-seeking candidate has reached a 20-session "
            "evaluation horizon. Risk-enforcement outcomes may be assessed, but "
            "they do not establish evidence of investment alpha."
        )
    elif twenty_day_candidate_cohorts < 20 or operational_gate != "ready_for_review":
        investment_evidence = "collecting"
        evidence_message = (
            "Outcome observations exist, but fewer than 20 distinct candidate/fill "
            "cohorts have 20-session marks or the weekly collection cadence has not "
            "remained current for at least 56 days."
        )
    else:
        investment_evidence = "reviewable"
        evidence_message = (
            "The minimum review gate is met. This is not proof of alpha: statistical, "
            "regime, tax, and execution review is still required before promotion."
        )

    return ProofOfValueReport(
        total_runs=total_runs,
        reproducible_runs=reproducible_runs,
        total_recommendations=total_recommendations,
        decision_counts={decision: count for decision, count in decision_rows},
        evaluated_outcomes=evaluated_outcomes,
        evaluated_recommendations=len(evaluated_recommendation_ids),
        horizon_evidence=horizon_evidence,
        first_run_at=first_run_at,
        last_run_at=last_run_at,
        operational_gate=operational_gate,
        investment_evidence=investment_evidence,
        evidence_message=evidence_message,
    )
