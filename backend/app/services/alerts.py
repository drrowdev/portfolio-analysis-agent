"""Alert generation and notification service."""

import logging
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.alert import Alert, AlertSeverity, AlertStatus, AlertType

logger = logging.getLogger(__name__)


async def create_alert(
    db: AsyncSession,
    alert_type: AlertType,
    title: str,
    message: str,
    severity: AlertSeverity = AlertSeverity.info,
    symbol: str | None = None,
    metadata: dict[str, Any] | None = None,
    notify: bool = True,
) -> Alert:
    """Create an alert and optionally push via ntfy.sh."""
    alert = Alert(
        alert_type=alert_type,
        title=title,
        message=message,
        severity=severity,
        status=AlertStatus.new,
        related_symbol=symbol,
        extra_data=metadata,
    )
    db.add(alert)
    await db.flush()
    await db.refresh(alert)

    if notify and settings.NTFY_TOPIC:
        await push_ntfy(title, message, severity)

    return alert


async def push_ntfy(
    title: str,
    message: str,
    severity: AlertSeverity = AlertSeverity.info,
) -> None:
    """Push notification via ntfy.sh."""
    priority_map = {
        AlertSeverity.info: "3",  # default
        AlertSeverity.warning: "4",  # high
        AlertSeverity.action: "5",  # urgent
    }

    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://ntfy.sh/{settings.NTFY_TOPIC}",
                headers={
                    "Title": title,
                    "Priority": priority_map.get(severity, "3"),
                    "Tags": (
                        "chart_with_upwards_trend"
                        if severity == AlertSeverity.info
                        else "warning"
                    ),
                },
                content=message,
                timeout=10,
            )
    except Exception as e:
        logger.error(f"Failed to send ntfy notification: {e}")


async def generate_alerts_from_analysis(
    db: AsyncSession, analysis: dict[str, Any]
) -> None:
    """Create alerts from Claude analysis results."""
    for rec in analysis.get("recommendations", []):
        if rec.get("priority") == "high":
            await create_alert(
                db=db,
                alert_type=AlertType.recommendation,
                title=f"Action: {rec.get('action', 'Recommendation')}",
                message=rec.get("rationale", ""),
                severity=AlertSeverity.action,
            )

    for insight in analysis.get("insights", []):
        if insight.get("severity") == "warning":
            await create_alert(
                db=db,
                alert_type=AlertType.news,
                title=insight.get("title", "Portfolio Alert"),
                message=insight.get("detail", ""),
                severity=AlertSeverity.warning,
            )


async def get_alerts(
    db: AsyncSession,
    status: AlertStatus | None = None,
    limit: int = 50,
) -> list[Alert]:
    """Get alerts, optionally filtered by status."""
    stmt = select(Alert).order_by(Alert.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(Alert.status == status)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def mark_alert_read(db: AsyncSession, alert_id: str) -> Alert | None:
    """Mark an alert as read."""
    stmt = select(Alert).where(Alert.id == alert_id)
    result = await db.execute(stmt)
    alert = result.scalar_one_or_none()
    if alert:
        alert.status = AlertStatus.read
        await db.flush()
    return alert


async def dismiss_alert(db: AsyncSession, alert_id: str) -> Alert | None:
    """Dismiss an alert."""
    stmt = select(Alert).where(Alert.id == alert_id)
    result = await db.execute(stmt)
    alert = result.scalar_one_or_none()
    if alert:
        alert.status = AlertStatus.dismissed
        await db.flush()
    return alert
