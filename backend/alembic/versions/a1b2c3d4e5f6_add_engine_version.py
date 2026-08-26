"""add engine_version to tax_calculations

Revision ID: a1b2c3d4e5f6
Revises: d0f1a2b3c4d5
Create Date: 2026-08-25 16:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "d0f1a2b3c4d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable on purpose: existing rows predate engine versioning and must read
    # as "legacy" rather than be back-stamped with a version that did not
    # produce them.
    op.add_column(
        "tax_calculations",
        sa.Column("engine_version", sa.String(20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tax_calculations", "engine_version")
