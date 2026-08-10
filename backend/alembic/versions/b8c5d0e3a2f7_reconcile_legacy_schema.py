"""reconcile tables previously created only by application startup

Revision ID: b8c5d0e3a2f7
Revises: a7d4e9c2f1b6
Create Date: 2026-08-07 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8c5d0e3a2f7"
down_revision: Union[str, None] = "a7d4e9c2f1b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "cache_entries" not in tables:
        op.create_table(
            "cache_entries",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("key", sa.String(length=200), nullable=False),
            sa.Column("value", sa.Text(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_cache_entries_key"),
            "cache_entries",
            ["key"],
            unique=True,
        )
    elif not any(
        index["name"] == op.f("ix_cache_entries_key")
        for index in inspector.get_indexes("cache_entries")
    ):
        op.create_index(
            op.f("ix_cache_entries_key"),
            "cache_entries",
            ["key"],
            unique=True,
        )

    if "investment_goals" not in tables:
        op.create_table(
            "investment_goals",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("target_amount_eur", sa.Numeric(14, 2), nullable=False),
            sa.Column("target_date", sa.Date(), nullable=False),
            sa.Column(
                "assumed_annual_return_pct",
                sa.Numeric(5, 2),
                nullable=False,
            ),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    if "symbol_metadata" not in tables:
        op.create_table(
            "symbol_metadata",
            sa.Column("symbol", sa.String(length=20), nullable=False),
            sa.Column("yahoo_symbol", sa.String(length=30), nullable=True),
            sa.Column("finnhub_symbol", sa.String(length=30), nullable=True),
            sa.Column("company_name", sa.String(length=255), nullable=True),
            sa.Column("isin", sa.String(length=12), nullable=True),
            sa.Column("sector", sa.String(length=100), nullable=True),
            sa.Column("industry", sa.String(length=255), nullable=True),
            sa.Column("country", sa.String(length=100), nullable=True),
            sa.Column("news_keywords", sa.JSON(), nullable=True),
            sa.Column(
                "has_finnhub_news",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            ),
            sa.Column(
                "has_yahoo_news",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            ),
            sa.Column(
                "is_crypto",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            ),
            sa.Column(
                "skip_in_aggregations",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("symbol"),
        )

    holding_columns = {
        column["name"] for column in inspector.get_columns("holdings")
    }
    missing_holding_columns = (
        ("avg_cost_basis_native", sa.Numeric()),
        ("total_cost_native", sa.Numeric()),
        ("price_change_pct", sa.Numeric()),
        ("market_state", sa.String(length=20)),
        ("extended_hours_price", sa.Numeric()),
        ("extended_hours_change_pct", sa.Numeric()),
    )
    for name, column_type in missing_holding_columns:
        if name not in holding_columns:
            op.add_column(
                "holdings",
                sa.Column(name, column_type, nullable=True),
            )

    analysis_run_columns = {
        column["name"] for column in inspector.get_columns("analysis_runs")
    }
    if "input_hash" not in analysis_run_columns:
        op.add_column(
            "analysis_runs",
            sa.Column("input_hash", sa.String(length=64), nullable=True),
        )
    if "input_json" not in analysis_run_columns:
        op.add_column(
            "analysis_runs",
            sa.Column("input_json", sa.JSON(), nullable=True),
        )
    if not any(
        index["name"] == op.f("ix_analysis_runs_input_hash")
        for index in inspector.get_indexes("analysis_runs")
    ):
        op.create_index(
            op.f("ix_analysis_runs_input_hash"),
            "analysis_runs",
            ["input_hash"],
            unique=False,
        )


def downgrade() -> None:
    # These objects may predate Alembic and contain user data. Never remove them
    # automatically when rolling the application revision back.
    pass
