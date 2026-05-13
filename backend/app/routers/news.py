"""News endpoints — list articles, trigger refresh, earnings calendar."""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.news import NewsArticle
from app.services.news_monitor import get_upcoming_earnings, poll_all_news

router = APIRouter(prefix="/news", tags=["news"])


@router.get("/")
async def list_news(
    symbol: Optional[str] = Query(None, description="Filter by stock symbol"),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List recent news articles, optionally filtered by symbol."""
    stmt = select(NewsArticle).order_by(NewsArticle.published_at.desc()).limit(limit)
    if symbol:
        stmt = stmt.where(NewsArticle.symbol == symbol)

    result = await db.execute(stmt)
    articles = result.scalars().all()
    return [
        {
            "id": str(a.id),
            "symbol": a.symbol,
            "title": a.title,
            "summary": a.summary,
            "url": a.url,
            "source": a.source,
            "published_at": a.published_at.isoformat() if a.published_at else None,
            "sentiment_score": float(a.sentiment_score) if a.sentiment_score is not None else None,
            "is_read": a.is_read,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in articles
    ]


@router.post("/refresh")
async def refresh_news(db: AsyncSession = Depends(get_db)) -> dict:
    """Trigger manual news refresh from all sources."""
    count = await poll_all_news(db)
    await db.commit()
    return {"new_articles": count}


@router.get("/earnings")
async def upcoming_earnings(db: AsyncSession = Depends(get_db)) -> list[dict]:
    """Get upcoming earnings calendar for portfolio companies."""
    return await get_upcoming_earnings(db)
