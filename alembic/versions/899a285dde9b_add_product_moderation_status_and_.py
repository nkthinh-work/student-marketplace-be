"""add_product_moderation_status_and_extend_moderation_actions

Revision ID: 899a285dde9b
Revises: d5a30bc546d1
Create Date: 2026-09-17 17:26:21.384463

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '899a285dde9b'
down_revision: Union[str, None] = 'd5a30bc546d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add moderation_status to products with server_default='CLEAR', NOT NULL, and check constraint
    op.add_column(
        'products',
        sa.Column('moderation_status', sa.String(length=10), server_default='CLEAR', nullable=False),
    )
    op.create_check_constraint(
        'chk_products_moderation_status',
        'products',
        "moderation_status IN ('CLEAR', 'BLOCKED')",
    )

    # 2. Extend moderation_actions constraints for PRODUCT target and PRODUCT_HIDE/PRODUCT_RESTORE actions
    op.drop_constraint('chk_moderation_actions_target_type', 'moderation_actions', type_='check')
    op.create_check_constraint(
        'chk_moderation_actions_target_type',
        'moderation_actions',
        "target_type IN ('USER', 'PRODUCT')",
    )

    op.drop_constraint('chk_moderation_actions_action_type', 'moderation_actions', type_='check')
    op.create_check_constraint(
        'chk_moderation_actions_action_type',
        'moderation_actions',
        "action_type IN ('USER_BAN', 'USER_UNBAN', 'PRODUCT_HIDE', 'PRODUCT_RESTORE')",
    )


def downgrade() -> None:
    # 1. Revert moderation_actions constraints back to USER and USER_BAN/USER_UNBAN
    op.drop_constraint('chk_moderation_actions_action_type', 'moderation_actions', type_='check')
    op.create_check_constraint(
        'chk_moderation_actions_action_type',
        'moderation_actions',
        "action_type IN ('USER_BAN', 'USER_UNBAN')",
    )

    op.drop_constraint('chk_moderation_actions_target_type', 'moderation_actions', type_='check')
    op.create_check_constraint(
        'chk_moderation_actions_target_type',
        'moderation_actions',
        "target_type IN ('USER')",
    )

    # 2. Drop moderation_status check constraint and column from products
    op.drop_constraint('chk_products_moderation_status', 'products', type_='check')
    op.drop_column('products', 'moderation_status')
