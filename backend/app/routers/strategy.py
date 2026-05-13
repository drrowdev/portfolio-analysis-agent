import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.strategy import Strategy
from app.schemas.strategy import StrategyCreate, StrategyRead, StrategyUpdate

router = APIRouter(prefix="/strategies", tags=["strategies"])


@router.get("/", response_model=list[StrategyRead])
async def list_strategies(db: AsyncSession = Depends(get_db)) -> list[Strategy]:
    result = await db.execute(select(Strategy))
    return list(result.scalars().all())


@router.get("/{strategy_id}", response_model=StrategyRead)
async def get_strategy(
    strategy_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Strategy:
    result = await db.execute(select(Strategy).where(Strategy.id == strategy_id))
    strategy = result.scalar_one_or_none()
    if strategy is None:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return strategy


@router.post("/", response_model=StrategyRead, status_code=201)
async def create_strategy(
    payload: StrategyCreate,
    db: AsyncSession = Depends(get_db),
) -> Strategy:
    strategy = Strategy(**payload.model_dump())
    db.add(strategy)
    await db.flush()
    await db.refresh(strategy)
    return strategy


@router.patch("/{strategy_id}", response_model=StrategyRead)
async def update_strategy(
    strategy_id: uuid.UUID,
    payload: StrategyUpdate,
    db: AsyncSession = Depends(get_db),
) -> Strategy:
    result = await db.execute(select(Strategy).where(Strategy.id == strategy_id))
    strategy = result.scalar_one_or_none()
    if strategy is None:
        raise HTTPException(status_code=404, detail="Strategy not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(strategy, field, value)

    await db.flush()
    await db.refresh(strategy)
    return strategy


@router.delete("/{strategy_id}", status_code=204)
async def delete_strategy(
    strategy_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(select(Strategy).where(Strategy.id == strategy_id))
    strategy = result.scalar_one_or_none()
    if strategy is None:
        raise HTTPException(status_code=404, detail="Strategy not found")
    await db.delete(strategy)
