import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel


class GoalCreate(BaseModel):
    name: str
    target_amount_eur: Decimal
    target_date: date
    assumed_annual_return_pct: Decimal = Decimal("7.0")
    notes: Optional[str] = None


class GoalUpdate(BaseModel):
    name: Optional[str] = None
    target_amount_eur: Optional[Decimal] = None
    target_date: Optional[date] = None
    assumed_annual_return_pct: Optional[Decimal] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class GoalRead(BaseModel):
    id: uuid.UUID
    name: str
    target_amount_eur: Decimal
    target_date: date
    assumed_annual_return_pct: Decimal
    notes: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class GoalProjection(BaseModel):
    """Computed projection for a single goal."""
    goal: GoalRead
    current_value_eur: Decimal
    progress_pct: Decimal                  # current / target * 100
    gap_eur: Decimal                       # target - current
    months_remaining: int
    projected_value_no_contributions: Decimal  # FV of current at assumed return
    shortfall_no_contributions: Decimal        # target - projected (0 if exceeds)
    required_monthly_eur: Decimal              # monthly to close the gap
