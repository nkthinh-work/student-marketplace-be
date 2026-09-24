"""add_reply_to_message_id_to_messages

Revision ID: 9f5916da6128
Revises: 899a285dde9b
Create Date: 2026-09-18 14:27:52.480161

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9f5916da6128'
down_revision: Union[str, None] = '899a285dde9b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'messages',
        sa.Column('reply_to_message_id', sa.BigInteger(), nullable=True)
    )
    op.create_foreign_key(
        'fk_messages_reply_to_message_id',
        'messages',
        'messages',
        ['reply_to_message_id'],
        ['message_id'],
        ondelete='SET NULL'
    )


def downgrade() -> None:
    op.drop_constraint('fk_messages_reply_to_message_id', 'messages', type_='foreignkey')
    op.drop_column('messages', 'reply_to_message_id')
