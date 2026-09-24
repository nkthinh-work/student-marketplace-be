"""create_conversations_and_messages

Revision ID: ff6a57a76040
Revises: 0b6255d0ebcd
Create Date: 2026-09-02 12:01:11.199669

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ff6a57a76040'
down_revision: Union[str, None] = '0b6255d0ebcd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create conversations table
    op.create_table(
        'conversations',
        sa.Column('conversation_id', sa.BigInteger(), sa.Identity(always=False, start=1), nullable=False),
        sa.Column('user_one_id', sa.BigInteger(), nullable=False),
        sa.Column('user_two_id', sa.BigInteger(), nullable=False),
        sa.Column('last_message_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('user_one_id < user_two_id', name='chk_conversations_user_order'),
        sa.ForeignKeyConstraint(['user_one_id'], ['users.user_id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['user_two_id'], ['users.user_id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('conversation_id'),
        sa.UniqueConstraint('user_one_id', 'user_two_id', name='ux_conversations_participants'),
    )

    # Indexes for keyset pagination on user's conversation inbox
    op.create_index(
        'ix_conversations_user_one_last_msg',
        'conversations',
        ['user_one_id', sa.text('last_message_at DESC'), sa.text('conversation_id DESC')],
        unique=False,
    )
    op.create_index(
        'ix_conversations_user_two_last_msg',
        'conversations',
        ['user_two_id', sa.text('last_message_at DESC'), sa.text('conversation_id DESC')],
        unique=False,
    )

    # 2. Create messages table
    op.create_table(
        'messages',
        sa.Column('message_id', sa.BigInteger(), sa.Identity(always=False, start=1), nullable=False),
        sa.Column('conversation_id', sa.BigInteger(), nullable=False),
        sa.Column('sender_id', sa.BigInteger(), nullable=False),
        sa.Column('type', sa.String(length=12), server_default='TEXT', nullable=False),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('product_id', sa.BigInteger(), nullable=True),
        sa.Column('order_id', sa.BigInteger(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('sent_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('read_at', sa.DateTime(), nullable=True),
        sa.CheckConstraint("type <> 'TEXT' OR content IS NOT NULL", name='chk_messages_type_content'),
        sa.CheckConstraint(
            "type IN ('TEXT', 'IMAGE', 'FILE', 'PRODUCT_CARD', 'ORDER_CARD', 'SYSTEM')",
            name='chk_messages_type_valid',
        ),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.conversation_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['sender_id'], ['users.user_id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['product_id'], ['products.product_id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['order_id'], ['orders.order_id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('message_id'),
    )

    # Indexes for messages
    op.create_index(
        'ix_messages_conversation_sent_desc',
        'messages',
        ['conversation_id', sa.text('sent_at DESC'), sa.text('message_id DESC')],
        unique=False,
    )
    op.create_index(
        'ix_messages_conversation_sender_read',
        'messages',
        ['conversation_id', 'sender_id', 'read_at'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_messages_conversation_sender_read', table_name='messages')
    op.drop_index('ix_messages_conversation_sent_desc', table_name='messages')
    op.drop_table('messages')

    op.drop_index('ix_conversations_user_two_last_msg', table_name='conversations')
    op.drop_index('ix_conversations_user_one_last_msg', table_name='conversations')
    op.drop_table('conversations')
