import enum
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Enum, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, generate_uuid


class AlertType(str, enum.Enum):
    price = "price"
    news = "news"
    earnings = "earnings"
    recommendation = "recommendation"
    rebalance = "rebalance"
    tax = "tax"


class AlertSeverity(str, enum.Enum):
    info = "info"
    warning = "warning"
    action = "action"


class AlertStatus(str, enum.Enum):
    new = "new"
    read = "read"
    dismissed = "dismissed"


class AnalysisType(str, enum.Enum):
    daily_summary = "daily_summary"
    rebalance = "rebalance"
    tax_optimization = "tax_optimization"
    news_impact = "news_impact"
    strategy_review = "strategy_review"


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    alert_type: Mapped[AlertType] = mapped_column(Enum(AlertType))
    title: Mapped[str] = mapped_column(String(500))
    message: Mapped[str] = mapped_column(Text)
    severity: Mapped[AlertSeverity] = mapped_column(Enum(AlertSeverity))
    status: Mapped[AlertStatus] = mapped_column(Enum(AlertStatus), default=AlertStatus.new)
    related_symbol: Mapped[Optional[str]] = mapped_column(String(20), default=None)
    extra_data: Mapped[Optional[dict[str, Any]]] = mapped_column(
        "metadata", JSON, default=None
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class AnalysisHistory(Base):
    __tablename__ = "analysis_history"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    analysis_type: Mapped[AnalysisType] = mapped_column(Enum(AnalysisType))
    content: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
