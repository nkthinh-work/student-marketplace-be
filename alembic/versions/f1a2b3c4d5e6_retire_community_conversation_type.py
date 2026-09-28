"""retire_community_conversation_type

Revision ID: f1a2b3c4d5e6
Revises: 4414f46b5404
Create Date: 2026-09-28 10:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, None] = '4414f46b5404'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Normalize all legacy COMMUNITY conversations to GROUP (preserving all messages, members, history)
    op.execute(sa.text("UPDATE conversations SET type = 'GROUP' WHERE type = 'COMMUNITY'"))

    # 2. Drop partial unique index for COMMUNITY singleton if exists
    op.drop_index('ux_conversations_single_community', table_name='conversations', if_exists=True)

    # 3. Update check constraint on conversations.type to only allow 'DIRECT' and 'GROUP'
    op.drop_constraint('chk_conversations_type', 'conversations', type_='check')
    op.create_check_constraint(
        'chk_conversations_type',
        'conversations',
        "type IN ('DIRECT', 'GROUP')"
    )


def downgrade() -> None:
    # 1. Restore check constraint allowing 'COMMUNITY'
    op.drop_constraint('chk_conversations_type', 'conversations', type_='check')
    op.create_check_constraint(
        'chk_conversations_type',
        'conversations',
        "type IN ('DIRECT', 'GROUP', 'COMMUNITY')"
    )

    # 2. Re-create partial unique index for COMMUNITY singleton
    op.create_index(
        'ux_conversations_single_community',
        'conversations',
        ['type'],
        unique=True,
        postgresql_where=sa.text("type = 'COMMUNITY'")
    )
