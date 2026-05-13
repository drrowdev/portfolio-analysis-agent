"""Portfolio analysis endpoints — Claude-powered insights."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.alert import AnalysisHistory, AnalysisType
from app.services import alerts as alerts_service
from app.services import analysis as analysis_service

router = APIRouter(prefix="/analysis", tags=["analysis"])


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
    await alerts_service.generate_alerts_from_analysis(db, result)
    return result


@router.post("/rebalance")
async def trigger_rebalance(db: AsyncSession = Depends(get_db)):
    """Get rebalancing recommendations."""
    result = await analysis_service.rebalance_recommendation(db)
    await alerts_service.generate_alerts_from_analysis(db, result)
    return result


@router.post("/tax-optimization")
async def trigger_tax_analysis(db: AsyncSession = Depends(get_db)):
    """Get tax optimization analysis."""
    result = await analysis_service.tax_optimization_analysis(db)
    await alerts_service.generate_alerts_from_analysis(db, result)
    return result


@router.post("/news-impact")
async def trigger_news_impact(db: AsyncSession = Depends(get_db)):
    """Analyze recent news impact on portfolio."""
    result = await analysis_service.news_impact_analysis(db)
    await alerts_service.generate_alerts_from_analysis(db, result)
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
