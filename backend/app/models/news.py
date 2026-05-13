import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, generate_uuid


class NewsArticle(Base):
    __tablename__ = "news_articles"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    symbol: Mapped[Optional[str]] = mapped_column(String(20), default=None)
    title: Mapped[str] = mapped_column(String(500))
    summary: Mapped[Optional[str]] = mapped_column(Text, default=None)
    url: Mapped[str] = mapped_column(String(2048))
    source: Mapped[str] = mapped_column(String(255))
    published_at: Mapped[datetime]
    sentiment_score: Mapped[Optional[Decimal]] = mapped_column(default=None)
    relevance_score: Mapped[Optional[Decimal]] = mapped_column(default=None)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
