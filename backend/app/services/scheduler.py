"""Background scheduler for periodic market data, news, and analysis jobs."""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.database import async_session_factory

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


# ---------------------------------------------------------------------------
# Job functions — each creates its own DB session
# ---------------------------------------------------------------------------

async def refresh_market_data_job() -> None:
    """Refresh market prices and FX rates for all holdings."""
    from app.routers.dashboard import invalidate_dashboard_cache
    from app.services.market_data import update_holdings_prices

    logger.info("[scheduler] Refreshing market data …")
    try:
        async with async_session_factory() as session:
            updated = await update_holdings_prices(session)
            await session.commit()
            invalidate_dashboard_cache()
            logger.info("[scheduler] Market data refreshed — %d holdings updated", updated)
    except Exception:
        logger.exception("[scheduler] Market data refresh failed")


async def poll_news_job() -> None:
    """Poll all configured news sources for new articles."""
    from app.services.news_monitor import poll_all_news

    logger.info("[scheduler] Polling news …")
    try:
        async with async_session_factory() as session:
            count = await poll_all_news(session)
            await session.commit()
            logger.info("[scheduler] News poll complete — %d new articles", count)
    except Exception:
        logger.exception("[scheduler] News poll failed")


async def daily_analysis_job() -> None:
    """Run daily portfolio summary after Helsinki market opens."""
    from app.services.analysis import daily_summary
    from app.services.alerts import generate_alerts_from_analysis

    logger.info("[scheduler] Running daily analysis …")
    try:
        async with async_session_factory() as session:
            result = await daily_summary(session)
            await generate_alerts_from_analysis(session, result)
            await session.commit()
            logger.info("[scheduler] Daily analysis complete")
    except Exception:
        logger.exception("[scheduler] Daily analysis failed")


async def check_dividends_job() -> None:
    """Check all holdings for new dividend payments via yfinance."""
    from app.services.dividend_detector import check_dividends

    logger.info("[scheduler] Checking for new dividends …")
    try:
        async with async_session_factory() as session:
            created = await check_dividends(session)
            await session.commit()
            if created:
                logger.info("[scheduler] Dividend check complete — %d new dividends recorded", created)
            else:
                logger.info("[scheduler] Dividend check complete — no new dividends")
    except Exception:
        logger.exception("[scheduler] Dividend check failed")


async def prefetch_performance_job() -> None:
    """Pre-warm the performance cache for common periods."""
    from app.services.portfolio import compute_performance_comparison

    logger.info("[scheduler] Pre-fetching performance data …")
    try:
        async with async_session_factory() as session:
            for period in ("1M", "3M", "1Y"):
                await compute_performance_comparison(session, period)
            logger.info("[scheduler] Performance cache warmed for 1M, 3M, 1Y")
    except Exception:
        logger.exception("[scheduler] Performance pre-fetch failed")


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

def setup_scheduler() -> None:
    """Register all recurring jobs and start the scheduler."""
    # Market data: every 5 min during US market hours (13:30-21:00 UTC),
    # every 15 min during extended hours (07:00-13:29 UTC), weekdays only.
    # Covers Helsinki (10:00-18:30 EEST) and US (09:30-16:00 ET)
    scheduler.add_job(
        refresh_market_data_job,
        "cron",
        day_of_week="mon-fri",
        hour="7-12",
        minute="*/15",
        id="market_data_extended",
        replace_existing=True,
    )
    scheduler.add_job(
        refresh_market_data_job,
        "cron",
        day_of_week="mon-fri",
        hour="13-21",
        minute="*/5",
        id="market_data_us",
        replace_existing=True,
    )

    # News polling: every 30 minutes (runs daily, news happens on weekends)
    scheduler.add_job(
        poll_news_job,
        "interval",
        minutes=30,
        id="news_poll",
        replace_existing=True,
    )

    # Daily analysis: 07:15 UTC weekdays (10:15 EEST, 15 min after Helsinki open)
    scheduler.add_job(
        daily_analysis_job,
        "cron",
        day_of_week="mon-fri",
        hour=7,
        minute=15,
        id="daily_analysis",
        replace_existing=True,
    )

    # Dividend detection: 08:00 UTC daily (11:00 EEST)
    # Runs daily to catch dividends from all markets
    scheduler.add_job(
        check_dividends_job,
        "cron",
        hour=8,
        minute=0,
        id="dividend_check",
        replace_existing=True,
    )

    # Pre-fetch performance data: every hour during market hours + on startup
    scheduler.add_job(
        prefetch_performance_job,
        "cron",
        day_of_week="mon-fri",
        hour="7-21",
        minute=5,
        id="prefetch_performance",
        replace_existing=True,
    )

    # Also run once at startup (after 15s delay to let DB connect)
    scheduler.add_job(
        refresh_market_data_job,
        "date",
        id="market_data_startup",
        replace_existing=True,
    )
    scheduler.add_job(
        prefetch_performance_job,
        "date",
        id="prefetch_performance_startup",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("[scheduler] Started with %d jobs", len(scheduler.get_jobs()))


def shutdown_scheduler() -> None:
    """Gracefully shut down the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("[scheduler] Shut down")
