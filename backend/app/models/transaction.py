import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Enum, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, generate_uuid


class TransactionType(str, enum.Enum):
    buy = "buy"
    sell = "sell"
    dividend = "dividend"
    espp_purchase = "espp_purchase"
    espp_sale = "espp_sale"
    deposit = "deposit"
    withdrawal = "withdrawal"


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    symbol: Mapped[str] = mapped_column(String(20))
    isin: Mapped[str] = mapped_column(String(12))
    instrument_name: Mapped[str] = mapped_column(String(255))
    currency: Mapped[str] = mapped_column(String(3))
    transaction_type: Mapped[TransactionType] = mapped_column(Enum(TransactionType))
    date: Mapped[date]
    quantity: Mapped[Decimal]
    price_native: Mapped[Decimal]
    price_eur: Mapped[Decimal]
    total_native: Mapped[Decimal]
    total_eur: Mapped[Decimal]
    fx_rate: Mapped[Optional[Decimal]] = mapped_column(default=None)
    fees: Mapped[Decimal] = mapped_column(default=Decimal("0"))
    notes: Mapped[Optional[str]] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)

    account: Mapped["Account"] = relationship(back_populates="transactions")  # noqa: F821
