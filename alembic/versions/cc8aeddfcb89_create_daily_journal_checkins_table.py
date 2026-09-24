"""create_daily_journal_checkins_table

Revision ID: cc8aeddfcb89
Revises: 484a13d1398a
Create Date: 2026-09-03 11:10:22.651691

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cc8aeddfcb89'
down_revision: Union[str, None] = '484a13d1398a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'daily_journal_checkins',
        sa.Column('checkin_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('checkin_date', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('checkin_id'),
        sa.UniqueConstraint('user_id', 'checkin_date', name='uq_daily_journal_checkins_user_date')
    )
    op.create_index('ix_daily_journal_checkins_user_id', 'daily_journal_checkins', ['user_id'], unique=False)

    # Backfill historical check-ins from existing daily_needs
    op.execute("""
        INSERT INTO daily_journal_checkins (
            user_id,
            checkin_date,
            created_at
        )
        SELECT
            user_id,
            note_date,
            MIN(created_at)
        FROM daily_needs
        GROUP BY user_id, note_date
        ON CONFLICT DO NOTHING;
    """)


def downgrade() -> None:
    op.drop_index('ix_daily_journal_checkins_user_id', table_name='daily_journal_checkins')
    op.drop_table('daily_journal_checkins')

