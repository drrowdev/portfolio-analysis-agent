import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import ForeignKey, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, generate_uuid


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    analysis_type: Mapped[str] = mapped_column(String(50), index=True)
    mode: Mapped[str] = mapped_column(String(20), default="shadow")
    status: Mapped[str] = mapped_column(String(20))
    model_name: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(50))
    snapshot_hash: Mapped[Optional[str]] = mapped_column(
        String(64), index=True, default=None
    )
    input_hash: Mapped[Optional[str]] = mapped_column(
        String(64), index=True, default=None
    )
    policy_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    data_quality_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    snapshot_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, default=None)
    input_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, default=None)
    result_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, default=None)
    error_message: Mapped[Optional[str]] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )

    recommendations: Mapped[list["ShadowRecommendation"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class ShadowRecommendation(Base):
    __tablename__ = "shadow_recommendations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), index=True
    )
    decision: Mapped[str] = mapped_column(String(20), index=True)
    symbol: Mapped[Optional[str]] = mapped_column(String(20), index=True, default=None)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    valid_until: Mapped[Optional[datetime]] = mapped_column(default=None)
    recommendation_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )

    run: Mapped[AnalysisRun] = relationship(back_populates="recommendations")
    outcomes: Mapped[list["RecommendationOutcome"]] = relationship(
        back_populates="recommendation", cascade="all, delete-orphan"
    )


class RecommendationOutcome(Base):
    __tablename__ = "recommendation_outcomes"
    __table_args__ = (
        UniqueConstraint(
            "recommendation_id",
            "horizon_trading_days",
            name="uq_recommendation_outcome_horizon",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=generate_uuid)
    recommendation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shadow_recommendations.id", ondelete="CASCADE"), index=True
    )
    horizon_trading_days: Mapped[int]
    evaluated_at: Mapped[datetime]
    outcome_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )

    recommendation: Mapped[ShadowRecommendation] = relationship(
        back_populates="outcomes"
    )
