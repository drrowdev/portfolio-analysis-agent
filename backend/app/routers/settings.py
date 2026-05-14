from datetime import date as date_type
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user_settings import UserSetting
from app.services.market_data import get_fx_rate

router = APIRouter(prefix="/settings", tags=["settings"])
fx_router = APIRouter(prefix="/fx", tags=["fx"])


class SettingValue(BaseModel):
    value: str


class SettingResponse(BaseModel):
    key: str
    value: str


class FxRateResponse(BaseModel):
    rate: float


@router.get("/{key}", response_model=SettingResponse)
async def get_setting(key: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(UserSetting).where(UserSetting.key == key))
    setting = result.scalar_one_or_none()
    if setting is None:
        raise HTTPException(status_code=404, detail=f"Setting '{key}' not found")
    return SettingResponse(key=setting.key, value=setting.value)


@router.put("/{key}", response_model=SettingResponse)
async def upsert_setting(key: str, body: SettingValue, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(UserSetting).where(UserSetting.key == key))
    setting = result.scalar_one_or_none()
    if setting is None:
        setting = UserSetting(key=key, value=body.value)
        db.add(setting)
    else:
        setting.value = body.value
    await db.flush()
    return SettingResponse(key=setting.key, value=setting.value)


@fx_router.get("/eurusd", response_model=FxRateResponse)
async def fx_eurusd(
    target_date: date_type | None = Query(default=None, alias="date"),
):
    """Return the EUR/USD rate (USD per 1 EUR).

    With ?date=YYYY-MM-DD, returns the close rate for that date (or the
    most recent prior trading day if the date is a weekend/holiday).
    Without a date, returns the latest available rate.
    """
    rate = await get_fx_rate("EURUSD", target_date=target_date)
    if rate is None:
        raise HTTPException(status_code=502, detail="Could not fetch EUR/USD rate")
    return FxRateResponse(rate=float(rate))
