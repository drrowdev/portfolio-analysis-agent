import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel

from app.models.strategy import RiskTolerance


class StrategyCreate(BaseModel):
    name: str
    description: str
    target_allocation: dict[str, Any]
    risk_tolerance: RiskTolerance
    rebalance_threshold_pct: Decimal = Decimal("5.0")
    tax_optimization_enabled: bool = True
    custom_rules: Optional[list[Any]] = None


class StrategyUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    target_allocation: Optional[dict[str, Any]] = None
    risk_tolerance: Optional[RiskTolerance] = None
    rebalance_threshold_pct: Optional[Decimal] = None
    tax_optimization_enabled: Optional[bool] = None
    custom_rules: Optional[list[Any]] = None
    is_active: Optional[bool] = None


class StrategyRead(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    target_allocation: dict[str, Any]
    risk_tolerance: RiskTolerance
    rebalance_threshold_pct: Decimal
    tax_optimization_enabled: bool
    custom_rules: Optional[list[Any]]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
