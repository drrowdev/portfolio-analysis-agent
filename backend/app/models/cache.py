"""Simple key-value cache table for expensive computations."""

import uuid
from datetime import datetime

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, generate_uuid


class CacheEntry(TimestampMixin, Base):
    __tablename__ = "cache_entries"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    value: Mapped[str] = mapped_column(Text)  # JSON-serialized
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
