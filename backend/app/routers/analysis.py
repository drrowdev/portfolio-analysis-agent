"""Portfolio analysis endpoints and proof-of-value controls."""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.alert import AnalysisHistory, AnalysisType
from app.schemas.analysis import (
    AnalysisSnapshot,
    GuidanceBrief,
    GuidanceRefreshResponse,
    GuidanceRefreshStep,
    ProofOfValueReport,
    ProofOfValuePolicy,
    ProofOfValuePolicyState,
    ShadowRunSummary,
)
from app.schemas.backtest import BacktestRunDetail, BacktestRunSummary, BacktestTrack
from app.services import alerts as alerts_service
from app.services import analysis as analysis_service
from app.services.analysis_snapshot import build_analysis_snapshot
from app.services.analysis_ledger import (
    list_recent_runs,
    proof_of_value_report as build_proof_of_value_report,
)
from app.services.proof_of_value import get_policy, save_policy
from app.services import backtests as backtest_service
from app.services.guidance import build_guidance
from app.services.market_data import update_holdings_prices

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.get("/policy", response_model=ProofOfValuePolicyState)
async def proof_of_value_policy(
    db: AsyncSession = Depends(get_db),
) -> ProofOfValuePolicyState:
    """Return the explicit benchmark, risk, and cost contract for shadow analysis."""
    return await get_policy(db)


@router.put("/policy", response_model=ProofOfValuePolicyState)
async def update_proof_of_value_policy(
    policy: ProofOfValuePolicy,
    db: AsyncSession = Depends(get_db),
) -> ProofOfValuePolicyState:
    """Replace the editable proof-of-value assumptions."""
    try:
        return await save_policy(db, policy)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/proof-of-value", response_model=AnalysisSnapshot)
async def proof_of_value_snapshot(
    db: AsyncSession = Depends(get_db),
) -> AnalysisSnapshot:
    """Build the reproducible data snapshot and deterministic risk scorecard."""
    return await build_analysis_snapshot(db)


@router.get("/guidance", response_model=GuidanceBrief)
async def deterministic_guidance(
    db: AsyncSession = Depends(get_db),
) -> GuidanceBrief:
    """Return the consumer cockpit without invoking an AI model."""
    return await build_guidance(db)


@router.post("/guidance/refresh", response_model=GuidanceRefreshResponse)
async def refresh_deterministic_guidance(
    db: AsyncSession = Depends(get_db),
) -> GuidanceRefreshResponse:
    """Refresh market prices and rebuild deterministic consumer guidance."""
    from app.routers.dashboard import invalidate_dashboard_cache

    updated = await update_holdings_prices(db)
    await db.commit()
    invalidate_dashboard_cache()
    guidance = await build_guidance(db)
    return GuidanceRefreshResponse(
        guidance=guidance,
        steps=[
            GuidanceRefreshStep(
                key="market_prices",
                status="completed",
                detail=(
                    f"Updated {updated} holding price"
                    f"{'' if updated == 1 else 's'}; snapshot freshness checks "
                    "determine whether the values are usable."
                ),
                updated_count=updated,
            ),
            GuidanceRefreshStep(
                key="guidance",
                status=(
                    "blocked"
                    if guidance.health.status == "blocked"
                    else "completed"
                ),
                detail=(
                    guidance.health.detail
                    if guidance.health.status == "blocked"
                    else "Portfolio checks rebuilt from the latest data."
                ),
            ),
        ],
    )


@router.get("/shadow-runs", response_model=list[ShadowRunSummary])
async def shadow_runs(
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
) -> list[ShadowRunSummary]:
    """Return immutable shadow-run metadata for proof-of-value reporting."""
    return await list_recent_runs(db, min(max(limit, 1), 100))


@router.get("/proof-of-value-report", response_model=ProofOfValueReport)
async def proof_of_value_report(
    db: AsyncSession = Depends(get_db),
) -> ProofOfValueReport:
    """Return the evidence-collection status without overstating investment value."""
    return await build_proof_of_value_report(db)


@router.get("/backtests/specification")
async def alpha_backtest_specification() -> dict:
    """Return the locked hypothesis and hashed point-in-time universe provenance."""
    return backtest_service.backtest_specification()


@router.get("/backtests/ledger-coverage")
async def alpha_backtest_ledger_coverage(
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Report concrete ledger reconciliation without note-based gap assumptions."""
    return await backtest_service.personal_ledger_coverage(db)


@router.post("/backtests/{track}")
async def trigger_alpha_backtest(
    track: BacktestTrack,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Run and persist one immutable, pre-registered backtest track."""
    return await backtest_service.run_backtest(db, track)


@router.get("/backtests", response_model=list[BacktestRunSummary])
async def alpha_backtest_runs(
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
) -> list[BacktestRunSummary]:
    """List immutable backtest evidence and blocked attempts."""
    return await backtest_service.list_backtest_runs(
        db,
        min(max(limit, 1), 100),
    )


@router.get("/backtests/runs/{run_id}", response_model=BacktestRunDetail)
async def alpha_backtest_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> BacktestRunDetail:
    """Return a persisted backtest result with hashes and assumptions."""
    result = await backtest_service.get_backtest_run(db, run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Backtest run not found.")
    return result


@router.get("/latest-daily-summary")
async def get_latest_daily_summary(db: AsyncSession = Depends(get_db)):
    """Get the most recent daily summary analysis."""
    stmt = (
        select(AnalysisHistory)
        .where(AnalysisHistory.analysis_type == AnalysisType.daily_summary)
        .order_by(AnalysisHistory.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        return None
    return {
        "id": str(row.id),
        "analysis_type": row.analysis_type.value,
        "content": row.content,
        "created_at": row.created_at.isoformat() + "Z",
    }


@router.post("/daily-summary")
async def trigger_daily_summary(db: AsyncSession = Depends(get_db)):
    """Trigger a daily portfolio analysis."""
    result = await analysis_service.daily_summary(db)
    await db.commit()
    try:
        await alerts_service.generate_alerts_from_analysis(db, result)
        await db.commit()
    except Exception:
        logger.exception("alert generation failed after daily_summary; analysis is saved")
        await db.rollback()
    return result


@router.post("/rebalance")
async def trigger_rebalance(db: AsyncSession = Depends(get_db)):
    """Get rebalancing recommendations."""
    result = await analysis_service.rebalance_recommendation(db)
    await db.commit()
    try:
        await alerts_service.generate_alerts_from_analysis(db, result)
        await db.commit()
    except Exception:
        logger.exception("alert generation failed after rebalance; analysis is saved")
        await db.rollback()
    return result


@router.post("/tax-optimization")
async def trigger_tax_analysis(db: AsyncSession = Depends(get_db)):
    """Get tax optimization analysis."""
    result = await analysis_service.tax_optimization_analysis(db)
    await db.commit()
    try:
        await alerts_service.generate_alerts_from_analysis(db, result)
        await db.commit()
    except Exception:
        logger.exception("alert generation failed after tax_optimization; analysis is saved")
        await db.rollback()
    return result


@router.post("/news-impact")
async def trigger_news_impact(db: AsyncSession = Depends(get_db)):
    """Analyze recent news impact on portfolio."""
    result = await analysis_service.news_impact_analysis(db)
    await db.commit()
    try:
        await alerts_service.generate_alerts_from_analysis(db, result)
        await db.commit()
    except Exception:
        logger.exception("alert generation failed after news_impact; analysis is saved")
        await db.rollback()
    return result


@router.get("/history")
async def analysis_history(
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    """Get analysis history."""
    stmt = (
        select(AnalysisHistory)
        .order_by(AnalysisHistory.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = list(result.scalars().all())
    return [
        {
            "id": str(r.id),
            "analysis_type": r.analysis_type.value,
            "content": r.content,
            "created_at": r.created_at.isoformat() + "Z",
        }
        for r in rows
    ]
