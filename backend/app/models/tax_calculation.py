"""Tax calculation persistence model."""

import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, generate_uuid


class TaxCalculation(Base):
    __tablename__ = "tax_calculations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    transaction_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("transactions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    symbol: Mapped[str] = mapped_column(String(20))
    sell_date: Mapped[date]
    quantity_sold: Mapped[str] = mapped_column(String(30))  # stored as string to avoid precision loss
    sell_price_eur: Mapped[str] = mapped_column(String(30))
    fees_eur: Mapped[str] = mapped_column(String(30), default="0")
    calculation_json: Mapped[str] = mapped_column(Text)  # full JSON result
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
