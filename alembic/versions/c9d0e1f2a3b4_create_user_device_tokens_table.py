"""create_user_device_tokens_table

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-10-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9d0e1f2a3b4'
down_revision: Union[str, None] = 'b8c9d0e1f2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'user_device_tokens',
        sa.Column('device_token_id', sa.BigInteger(), sa.Identity(always=False, start=1), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('fcm_token', sa.Text(), nullable=False),
        sa.Column('device_info', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('device_token_id'),
        sa.UniqueConstraint('fcm_token', name='uq_user_device_tokens_fcm_token')
    )
    op.create_index('ix_user_device_tokens_user_id', 'user_device_tokens', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_user_device_tokens_user_id', table_name='user_device_tokens')
    op.drop_table('user_device_tokens')
