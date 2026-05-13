"""add user_settings table

Revision ID: a3b8f1d24e90
Revises: c9e846a57614
Create Date: 2026-07-03 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3b8f1d24e90'
down_revision: Union[str, None] = 'c9e846a57614'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('user_settings',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('key', sa.String(length=100), nullable=False),
        sa.Column('value', sa.String(length=500), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key'),
    )
    op.create_index(op.f('ix_user_settings_key'), 'user_settings', ['key'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_user_settings_key'), table_name='user_settings')
    op.drop_table('user_settings')
