"""Alert management endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.alert import AlertStatus
from app.services import alerts as alerts_service

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("/")
async def list_alerts(
    status: str | None = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """List alerts, optionally filtered by status."""
    alert_status = AlertStatus(status) if status else None
    results = await alerts_service.get_alerts(db, status=alert_status, limit=limit)
    return [
        {
            "id": str(a.id),
            "alert_type": a.alert_type.value,
            "title": a.title,
            "message": a.message,
            "severity": a.severity.value,
            "status": a.status.value,
            "related_symbol": a.related_symbol,
            "extra_data": a.extra_data,
            "created_at": a.created_at.isoformat(),
        }
        for a in results
    ]


@router.put("/{alert_id}/read")
async def mark_read(
    alert_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Mark an alert as read."""
    alert = await alerts_service.mark_alert_read(db, str(alert_id))
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"id": str(alert.id), "status": alert.status.value}


@router.put("/{alert_id}/dismiss")
async def dismiss(
    alert_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Dismiss an alert."""
    alert = await alerts_service.dismiss_alert(db, str(alert_id))
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"id": str(alert.id), "status": alert.status.value}
