"""create_notifications_table

Revision ID: 0ec5c6081b6d
Revises: e58355f24d58
Create Date: 2026-09-14 13:46:12.938707

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0ec5c6081b6d'
down_revision: Union[str, None] = 'e58355f24d58'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'notifications',
        sa.Column('notification_id', sa.BigInteger(), sa.Identity(always=False, start=1), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('type', sa.String(length=20), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('ref_type', sa.String(length=20), nullable=True),
        sa.Column('ref_id', sa.BigInteger(), nullable=True),
        sa.Column('is_read', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint(
            "type IN ('NEW_ORDER','ORDER_STATUS','NEW_MESSAGE','NEW_REVIEW','AUCTION_BID','AUCTION_OUTBID','AUCTION_WON','AUCTION_ENDED','SYSTEM')",
            name='chk_notifications_type'
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('notification_id')
    )
    op.create_index(
        'ix_notifications_user_read_created',
        'notifications',
        ['user_id', 'is_read', 'created_at'],
        unique=False
    )


def downgrade() -> None:
    op.drop_index('ix_notifications_user_read_created', table_name='notifications')
    op.drop_table('notifications')
