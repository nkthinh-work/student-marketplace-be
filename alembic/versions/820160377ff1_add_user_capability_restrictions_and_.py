"""add_user_capability_restrictions_and_extend_moderation_actions

Revision ID: 820160377ff1
Revises: 9f5916da6128
Create Date: 2026-09-21 02:26:24.339249

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '820160377ff1'
down_revision: Union[str, None] = '9f5916da6128'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create table user_capability_restrictions
    op.create_table(
        'user_capability_restrictions',
        sa.Column('restriction_id', sa.BigInteger(), sa.Identity(always=False, start=1), nullable=False),
        sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.user_id', ondelete='RESTRICT'), nullable=False),
        sa.Column('source_report_id', sa.BigInteger(), sa.ForeignKey('reports.report_id', ondelete='RESTRICT'), nullable=False),
        sa.Column('imposed_by', sa.BigInteger(), sa.ForeignKey('users.user_id', ondelete='RESTRICT'), nullable=False),
        sa.Column('capability', sa.String(length=10), nullable=False),
        sa.Column('starts_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.Column('revoked_by', sa.BigInteger(), sa.ForeignKey('users.user_id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('restriction_id'),
        sa.CheckConstraint("capability IN ('BUY', 'SELL')", name='chk_user_capability_restrictions_capability'),
        sa.CheckConstraint('expires_at IS NULL OR expires_at > starts_at', name='chk_user_capability_restrictions_expires_at'),
        sa.CheckConstraint('revoked_at IS NULL OR revoked_at >= starts_at', name='chk_user_capability_restrictions_revoked_at'),
    )

    op.create_index(
        'ix_user_capability_restrictions_user_cap',
        'user_capability_restrictions',
        ['user_id', 'capability'],
    )
    op.create_index(
        'ix_user_capability_restrictions_source_report',
        'user_capability_restrictions',
        ['source_report_id'],
    )
    op.create_index(
        'ix_user_capability_restrictions_active_lookup',
        'user_capability_restrictions',
        ['user_id', 'capability', 'starts_at', 'expires_at', 'revoked_at'],
    )

    # 2. Extend moderation_actions action_type constraint
    op.drop_constraint('chk_moderation_actions_action_type', 'moderation_actions', type_='check')
    op.create_check_constraint(
        'chk_moderation_actions_action_type',
        'moderation_actions',
        "action_type IN ('USER_BAN', 'USER_UNBAN', 'PRODUCT_HIDE', 'PRODUCT_RESTORE', 'BUY_RESTRICT', 'BUY_RESTORE', 'SELL_RESTRICT', 'SELL_RESTORE')",
    )


def downgrade() -> None:
    # 1. Revert moderation_actions action_type constraint
    op.drop_constraint('chk_moderation_actions_action_type', 'moderation_actions', type_='check')
    op.create_check_constraint(
        'chk_moderation_actions_action_type',
        'moderation_actions',
        "action_type IN ('USER_BAN', 'USER_UNBAN', 'PRODUCT_HIDE', 'PRODUCT_RESTORE')",
    )

    # 2. Drop user_capability_restrictions table and indexes
    op.drop_index('ix_user_capability_restrictions_active_lookup', table_name='user_capability_restrictions')
    op.drop_index('ix_user_capability_restrictions_source_report', table_name='user_capability_restrictions')
    op.drop_index('ix_user_capability_restrictions_user_cap', table_name='user_capability_restrictions')
    op.drop_table('user_capability_restrictions')
