import uuid
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import Date, Numeric, String, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, generate_uuid


class InvestmentGoal(TimestampMixin, Base):
    __tablename__ = "investment_goals"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(255))
    target_amount_eur: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    target_date: Mapped[date] = mapped_column(Date)
    assumed_annual_return_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("7.0"))
    notes: Mapped[Optional[str]] = mapped_column(Text, default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
