"""create_daily_needs_table

Revision ID: 484a13d1398a
Revises: 9f1a2b3c4d5e
Create Date: 2026-09-03 00:41:03.142668

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '484a13d1398a'
down_revision: Union[str, None] = '9f1a2b3c4d5e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'daily_needs',
        sa.Column('daily_need_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('note_date', sa.Date(), nullable=False),
        sa.Column('content', sa.String(length=120), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('daily_need_id'),
        sa.UniqueConstraint('user_id', 'note_date', name='uq_daily_needs_user_date')
    )
    op.create_index('ix_daily_needs_user_id', 'daily_needs', ['user_id'], unique=False)
    op.create_index(
        'ix_daily_needs_today_recency',
        'daily_needs',
        ['note_date', 'updated_at', 'daily_need_id'],
        unique=False
    )


def downgrade() -> None:
    op.drop_index('ix_daily_needs_today_recency', table_name='daily_needs')
    op.drop_index('ix_daily_needs_user_id', table_name='daily_needs')
    op.drop_table('daily_needs')
