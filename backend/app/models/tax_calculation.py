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

    # Which build of the tax engine produced ``calculation_json``. The engine has
    # been corrected before (per-lot hankintameno-olettama, USD→EUR conversion,
    # calendar-based 10-year boundary), which silently changed the tax on sales
    # that had already been declared and paid. Stamping the version makes those
    # rows identifiable instead of letting the change pass unnoticed. Rows saved
    # before this column existed read as NULL and are surfaced as "legacy".
    engine_version: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # Declaration tracking: has the per-sale ennakkovero been declared/paid in
    # OmaVero, and (optionally) the actual amount/date the user paid. Used to
    # show how much of the year's prepayment is still outstanding.
    declared_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    paid_amount_eur: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    paid_date: Mapped[Optional[date]] = mapped_column(nullable=True)
