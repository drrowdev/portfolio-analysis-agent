"""add shadow analysis ledger

Revision ID: a7d4e9c2f1b6
Revises: f6b7c8d9e0a1
Create Date: 2026-08-07 11:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7d4e9c2f1b6"
down_revision: Union[str, None] = "f6b7c8d9e0a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "analysis_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("analysis_type", sa.String(length=50), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("model_name", sa.String(length=100), nullable=False),
        sa.Column("prompt_version", sa.String(length=50), nullable=False),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=True),
        sa.Column("policy_json", sa.JSON(), nullable=False),
        sa.Column("data_quality_json", sa.JSON(), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_analysis_runs_analysis_type"),
        "analysis_runs",
        ["analysis_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_analysis_runs_snapshot_hash"),
        "analysis_runs",
        ["snapshot_hash"],
        unique=False,
    )

    op.create_table(
        "shadow_recommendations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("valid_until", sa.DateTime(), nullable=True),
        sa.Column("recommendation_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["analysis_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_shadow_recommendations_decision"),
        "shadow_recommendations",
        ["decision"],
        unique=False,
    )
    op.create_index(
        op.f("ix_shadow_recommendations_run_id"),
        "shadow_recommendations",
        ["run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_shadow_recommendations_status"),
        "shadow_recommendations",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_shadow_recommendations_symbol"),
        "shadow_recommendations",
        ["symbol"],
        unique=False,
    )

    op.create_table(
        "recommendation_outcomes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recommendation_id", sa.Uuid(), nullable=False),
        sa.Column("horizon_trading_days", sa.Integer(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(), nullable=False),
        sa.Column("outcome_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["recommendation_id"],
            ["shadow_recommendations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "recommendation_id",
            "horizon_trading_days",
            name="uq_recommendation_outcome_horizon",
        ),
    )
    op.create_index(
        op.f("ix_recommendation_outcomes_recommendation_id"),
        "recommendation_outcomes",
        ["recommendation_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_recommendation_outcomes_recommendation_id"),
        table_name="recommendation_outcomes",
    )
    op.drop_table("recommendation_outcomes")
    op.drop_index(
        op.f("ix_shadow_recommendations_symbol"),
        table_name="shadow_recommendations",
    )
    op.drop_index(
        op.f("ix_shadow_recommendations_status"),
        table_name="shadow_recommendations",
    )
    op.drop_index(
        op.f("ix_shadow_recommendations_run_id"),
        table_name="shadow_recommendations",
    )
    op.drop_index(
        op.f("ix_shadow_recommendations_decision"),
        table_name="shadow_recommendations",
    )
    op.drop_table("shadow_recommendations")
    op.drop_index(
        op.f("ix_analysis_runs_snapshot_hash"), table_name="analysis_runs"
    )
    op.drop_index(
        op.f("ix_analysis_runs_analysis_type"), table_name="analysis_runs"
    )
    op.drop_table("analysis_runs")
