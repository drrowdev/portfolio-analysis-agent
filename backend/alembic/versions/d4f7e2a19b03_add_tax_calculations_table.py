"""add tax_calculations table

Revision ID: d4f7e2a19b03
Revises: a3b8f1d24e90
Create Date: 2026-05-06 18:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d4f7e2a19b03"
down_revision: Union[str, None] = "a3b8f1d24e90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tax_calculations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=True),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("sell_date", sa.Date(), nullable=False),
        sa.Column("quantity_sold", sa.String(30), nullable=False),
        sa.Column("sell_price_eur", sa.String(30), nullable=False),
        sa.Column("fees_eur", sa.String(30), nullable=False, server_default="0"),
        sa.Column("calculation_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["transaction_id"], ["transactions.id"], ondelete="SET NULL"
        ),
    )
    op.create_index("ix_tax_calculations_transaction_id", "tax_calculations", ["transaction_id"])


def downgrade() -> None:
    op.drop_index("ix_tax_calculations_transaction_id", "tax_calculations")
    op.drop_table("tax_calculations")
