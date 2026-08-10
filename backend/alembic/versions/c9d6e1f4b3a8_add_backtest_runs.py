"""add immutable backtest runs

Revision ID: c9d6e1f4b3a8
Revises: b8c5d0e3a2f7
Create Date: 2026-08-09 17:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c9d6e1f4b3a8"
down_revision: Union[str, None] = "b8c5d0e3a2f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("track", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("spec_version", sa.String(length=80), nullable=False),
        sa.Column("specification_hash", sa.String(length=64), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("policy_json", sa.JSON(), nullable=False),
        sa.Column("data_manifest_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "track",
        "status",
        "spec_version",
        "specification_hash",
        "input_hash",
    ):
        op.create_index(
            op.f(f"ix_backtest_runs_{column}"),
            "backtest_runs",
            [column],
            unique=False,
        )


def downgrade() -> None:
    for column in (
        "input_hash",
        "specification_hash",
        "spec_version",
        "status",
        "track",
    ):
        op.drop_index(
            op.f(f"ix_backtest_runs_{column}"),
            table_name="backtest_runs",
        )
    op.drop_table("backtest_runs")
