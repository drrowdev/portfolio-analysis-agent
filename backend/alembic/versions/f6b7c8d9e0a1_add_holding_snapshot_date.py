"""add holding snapshot date

Revision ID: f6b7c8d9e0a1
Revises: e5c1a7f3b2d8
Create Date: 2026-08-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f6b7c8d9e0a1"
down_revision: Union[str, None] = "e5c1a7f3b2d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "holdings",
        sa.Column("snapshot_date", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("holdings", "snapshot_date")
