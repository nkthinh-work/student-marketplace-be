"""create_moderation_actions_table

Revision ID: d5a30bc546d1
Revises: 73a5dd9cec95
Create Date: 2026-09-17 13:22:43.570843

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd5a30bc546d1'
down_revision: Union[str, None] = '73a5dd9cec95'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'moderation_actions',
        sa.Column('moderation_action_id', sa.BigInteger(), sa.Identity(always=False, start=1), nullable=False),
        sa.Column('report_id', sa.BigInteger(), nullable=False),
        sa.Column('admin_id', sa.BigInteger(), nullable=False),
        sa.Column('target_type', sa.String(length=10), nullable=False),
        sa.Column('target_id', sa.BigInteger(), nullable=False),
        sa.Column('action_type', sa.String(length=20), nullable=False),
        sa.Column('previous_status', sa.String(length=20), nullable=False),
        sa.Column('new_status', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("target_type IN ('USER')", name='chk_moderation_actions_target_type'),
        sa.CheckConstraint("action_type IN ('USER_BAN', 'USER_UNBAN')", name='chk_moderation_actions_action_type'),
        sa.ForeignKeyConstraint(['report_id'], ['reports.report_id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['admin_id'], ['users.user_id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('moderation_action_id'),
    )
    op.create_index(
        'ix_moderation_actions_report_history',
        'moderation_actions',
        ['report_id', 'created_at', 'moderation_action_id'],
        unique=False,
    )
    op.create_index(
        'ix_moderation_actions_target_history',
        'moderation_actions',
        ['target_type', 'target_id', 'created_at', 'moderation_action_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_moderation_actions_target_history', table_name='moderation_actions')
    op.drop_index('ix_moderation_actions_report_history', table_name='moderation_actions')
    op.drop_table('moderation_actions')
