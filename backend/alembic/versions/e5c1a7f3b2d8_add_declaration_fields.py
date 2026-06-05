"""add declaration tracking fields to tax_calculations

Revision ID: e5c1a7f3b2d8
Revises: d4f7e2a19b03
Create Date: 2026-06-05 11:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e5c1a7f3b2d8"
down_revision: Union[str, None] = "d4f7e2a19b03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tax_calculations", sa.Column("declared_at", sa.DateTime(), nullable=True))
    op.add_column("tax_calculations", sa.Column("paid_amount_eur", sa.String(30), nullable=True))
    op.add_column("tax_calculations", sa.Column("paid_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("tax_calculations", "paid_date")
    op.drop_column("tax_calculations", "paid_amount_eur")
    op.drop_column("tax_calculations", "declared_at")
