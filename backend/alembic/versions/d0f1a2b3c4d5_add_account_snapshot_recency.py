"""add account snapshot recency

Revision ID: d0f1a2b3c4d5
Revises: c9d6e1f4b3a8
Create Date: 2026-08-09 20:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d0f1a2b3c4d5"
down_revision: Union[str, None] = "c9d6e1f4b3a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("last_holdings_snapshot_date", sa.Date(), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE accounts
            SET last_holdings_snapshot_date = (
                SELECT MAX(holdings.snapshot_date)
                FROM holdings
                WHERE holdings.account_id = accounts.id
            )
            WHERE EXISTS (
                SELECT 1
                FROM holdings
                WHERE holdings.account_id = accounts.id
                  AND holdings.snapshot_date IS NOT NULL
            )
            """
        )
    )


def downgrade() -> None:
    op.drop_column("accounts", "last_holdings_snapshot_date")
