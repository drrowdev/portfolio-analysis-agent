import enum
import uuid
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import Boolean, Enum, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, generate_uuid


class RiskTolerance(str, enum.Enum):
    conservative = "conservative"
    moderate = "moderate"
    aggressive = "aggressive"


class Strategy(TimestampMixin, Base):
    __tablename__ = "strategies"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    target_allocation: Mapped[dict[str, Any]] = mapped_column(JSON)
    risk_tolerance: Mapped[RiskTolerance] = mapped_column(Enum(RiskTolerance))
    rebalance_threshold_pct: Mapped[Decimal] = mapped_column(default=Decimal("5.0"))
    tax_optimization_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    custom_rules: Mapped[Optional[list[Any]]] = mapped_column(JSON, default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
