import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import BigInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, generate_uuid


class MarketPrice(Base):
    __tablename__ = "market_prices"
    __table_args__ = (UniqueConstraint("symbol", "date", name="uq_market_price_symbol_date"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    symbol: Mapped[str] = mapped_column(String(20))
    date: Mapped[date]
    open: Mapped[Decimal]
    high: Mapped[Decimal]
    low: Mapped[Decimal]
    close: Mapped[Decimal]
    volume: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))


class FxRate(Base):
    __tablename__ = "fx_rates"
    __table_args__ = (UniqueConstraint("pair", "date", name="uq_fx_rate_pair_date"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    pair: Mapped[str] = mapped_column(String(10))  # e.g., "EURUSD"
    date: Mapped[date]
    rate: Mapped[Decimal]
