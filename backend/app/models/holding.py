import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, generate_uuid


class Holding(TimestampMixin, Base):
    __tablename__ = "holdings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    symbol: Mapped[str] = mapped_column(String(20))
    isin: Mapped[str] = mapped_column(String(12))
    instrument_name: Mapped[str] = mapped_column(String(255))
    exchange: Mapped[Optional[str]] = mapped_column(String(50), default=None)
    currency: Mapped[str] = mapped_column(String(3))
    total_quantity: Mapped[Decimal]
    avg_cost_basis_eur: Mapped[Decimal]
    total_cost_eur: Mapped[Decimal]
    current_price_native: Mapped[Optional[Decimal]] = mapped_column(default=None)
    current_price_eur: Mapped[Optional[Decimal]] = mapped_column(default=None)
    current_value_eur: Mapped[Optional[Decimal]] = mapped_column(default=None)
    unrealized_pnl_eur: Mapped[Optional[Decimal]] = mapped_column(default=None)
    unrealized_pnl_pct: Mapped[Optional[Decimal]] = mapped_column(default=None)
    portfolio_weight_pct: Mapped[Optional[Decimal]] = mapped_column(default=None)
    price_change_pct: Mapped[Optional[Decimal]] = mapped_column(default=None)
    market_state: Mapped[Optional[str]] = mapped_column(String(20), default=None)
    extended_hours_price: Mapped[Optional[Decimal]] = mapped_column(default=None)
    extended_hours_change_pct: Mapped[Optional[Decimal]] = mapped_column(default=None)
    last_price_update: Mapped[Optional[datetime]] = mapped_column(default=None)

    account: Mapped["Account"] = relationship(back_populates="holdings")  # noqa: F821
