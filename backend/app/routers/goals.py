import uuid
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.goal import InvestmentGoal
from app.models.account import Account
from app.schemas.goal import GoalCreate, GoalRead, GoalUpdate, GoalProjection

router = APIRouter(prefix="/goals", tags=["goals"])


def _compute_projection(
    goal: InvestmentGoal,
    current_value: Decimal,
) -> GoalProjection:
    """Pure-math projection for a goal given current portfolio value."""
    today = date.today()
    target = goal.target_date

    # Months remaining (minimum 1 to avoid div-by-zero)
    months_remaining = max(
        (target.year - today.year) * 12 + (target.month - today.month), 1
    )

    # Monthly return from annual assumed return
    annual_r = float(goal.assumed_annual_return_pct) / 100.0
    monthly_r = (1 + annual_r) ** (1 / 12) - 1

    # Future value of current portfolio with no extra contributions
    fv_current = float(current_value) * ((1 + monthly_r) ** months_remaining)

    target_f = float(goal.target_amount_eur)
    shortfall = max(target_f - fv_current, 0.0)

    # Required monthly contribution (future-value-of-annuity formula)
    if monthly_r > 0 and shortfall > 0:
        # FV of annuity: PMT * [((1+r)^n - 1) / r]
        annuity_factor = ((1 + monthly_r) ** months_remaining - 1) / monthly_r
        required_monthly = shortfall / annuity_factor
    else:
        required_monthly = 0.0

    progress = (
        (float(current_value) / target_f * 100) if target_f > 0 else Decimal(0)
    )
    gap = target_f - float(current_value)

    D = Decimal
    return GoalProjection(
        goal=GoalRead.model_validate(goal),
        current_value_eur=current_value.quantize(D("0.01"), ROUND_HALF_UP),
        progress_pct=D(str(progress)).quantize(D("0.1"), ROUND_HALF_UP),
        gap_eur=D(str(gap)).quantize(D("0.01"), ROUND_HALF_UP),
        months_remaining=months_remaining,
        projected_value_no_contributions=D(str(fv_current)).quantize(D("0.01"), ROUND_HALF_UP),
        shortfall_no_contributions=D(str(shortfall)).quantize(D("0.01"), ROUND_HALF_UP),
        required_monthly_eur=D(str(required_monthly)).quantize(D("0.01"), ROUND_HALF_UP),
    )


async def _current_portfolio_value(db: AsyncSession) -> Decimal:
    """Sum current_value_eur across all holdings."""
    stmt = select(Account).options(selectinload(Account.holdings))
    result = await db.execute(stmt)
    accounts = list(result.scalars().all())
    total = Decimal("0")
    for acct in accounts:
        for h in acct.holdings:
            if h.current_value_eur is not None:
                total += h.current_value_eur
    return total


# ── CRUD ──────────────────────────────────────────────────────────────────


@router.get("/", response_model=list[GoalProjection])
async def list_goals(db: AsyncSession = Depends(get_db)) -> list[GoalProjection]:
    """Return all goals with live projections."""
    result = await db.execute(select(InvestmentGoal))
    goals = list(result.scalars().all())
    if not goals:
        return []

    current_value = await _current_portfolio_value(db)
    return [_compute_projection(g, current_value) for g in goals]


@router.get("/{goal_id}", response_model=GoalProjection)
async def get_goal(
    goal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> GoalProjection:
    result = await db.execute(select(InvestmentGoal).where(InvestmentGoal.id == goal_id))
    goal = result.scalar_one_or_none()
    if goal is None:
        raise HTTPException(status_code=404, detail="Goal not found")
    current_value = await _current_portfolio_value(db)
    return _compute_projection(goal, current_value)


@router.post("/", response_model=GoalProjection, status_code=201)
async def create_goal(
    payload: GoalCreate,
    db: AsyncSession = Depends(get_db),
) -> GoalProjection:
    goal = InvestmentGoal(**payload.model_dump())
    db.add(goal)
    await db.flush()
    await db.refresh(goal)
    current_value = await _current_portfolio_value(db)
    return _compute_projection(goal, current_value)


@router.patch("/{goal_id}", response_model=GoalProjection)
async def update_goal(
    goal_id: uuid.UUID,
    payload: GoalUpdate,
    db: AsyncSession = Depends(get_db),
) -> GoalProjection:
    result = await db.execute(select(InvestmentGoal).where(InvestmentGoal.id == goal_id))
    goal = result.scalar_one_or_none()
    if goal is None:
        raise HTTPException(status_code=404, detail="Goal not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(goal, field, value)

    await db.flush()
    await db.refresh(goal)
    current_value = await _current_portfolio_value(db)
    return _compute_projection(goal, current_value)


@router.delete("/{goal_id}", status_code=204)
async def delete_goal(
    goal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(select(InvestmentGoal).where(InvestmentGoal.id == goal_id))
    goal = result.scalar_one_or_none()
    if goal is None:
        raise HTTPException(status_code=404, detail="Goal not found")
    await db.delete(goal)
