"""social chat and group conversations

Revision ID: 8c3d4e5f6a7b
Revises: 7a1b2c3d4e5f
Create Date: 2026-09-02 16:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '8c3d4e5f6a7b'
down_revision: Union[str, None] = '7a1b2c3d4e5f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Alter conversations table
    # Add new columns: type, title, description, avatar_url, direct_pair_key
    op.add_column(
        'conversations',
        sa.Column('type', sa.String(length=12), server_default='DIRECT', nullable=False)
    )
    op.add_column(
        'conversations',
        sa.Column('title', sa.String(length=80), nullable=True)
    )
    op.add_column(
        'conversations',
        sa.Column('description', sa.String(length=300), nullable=True)
    )
    op.add_column(
        'conversations',
        sa.Column('avatar_url', sa.Text(), nullable=True)
    )
    op.add_column(
        'conversations',
        sa.Column('direct_pair_key', sa.String(length=64), nullable=True)
    )

    # Add CHECK constraint for conversation type
    op.create_check_constraint(
        'chk_conversations_type',
        'conversations',
        "type IN ('DIRECT', 'GROUP', 'COMMUNITY')"
    )

    # Backfill direct_pair_key and type for existing conversations
    op.execute(
        sa.text(
            "UPDATE conversations "
            "SET type = 'DIRECT', direct_pair_key = user_one_id || ':' || user_two_id "
            "WHERE user_one_id IS NOT NULL AND user_two_id IS NOT NULL"
        )
    )

    # Create unique constraint on direct_pair_key for DIRECT conversations
    op.create_unique_constraint(
        'uq_conversations_direct_pair_key',
        'conversations',
        ['direct_pair_key']
    )

    # Create partial unique index for COMMUNITY singleton
    op.create_index(
        'ux_conversations_single_community',
        'conversations',
        ['type'],
        unique=True,
        postgresql_where=sa.text("type = 'COMMUNITY'")
    )

    # Make legacy user_one_id and user_two_id nullable so GROUP/COMMUNITY rows do not require them
    op.alter_column('conversations', 'user_one_id', nullable=True)
    op.alter_column('conversations', 'user_two_id', nullable=True)

    # Drop legacy constraints on user_one_id/user_two_id
    op.drop_constraint('chk_conversations_user_order', 'conversations', type_='check')
    op.drop_constraint('ux_conversations_participants', 'conversations', type_='unique')

    # 2. Create conversation_members table
    op.create_table(
        'conversation_members',
        sa.Column('conversation_id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('role', sa.String(length=10), server_default='MEMBER', nullable=False),
        sa.Column('joined_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('left_at', sa.DateTime(), nullable=True),
        sa.Column('last_read_message_id', sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.conversation_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['last_read_message_id'], ['messages.message_id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('conversation_id', 'user_id'),
        sa.CheckConstraint("role IN ('OWNER', 'ADMIN', 'MEMBER')", name='chk_conversation_members_role')
    )
    op.create_index(
        'ix_conversation_members_user_active',
        'conversation_members',
        ['user_id', 'left_at']
    )
    op.create_index(
        'ix_conversation_members_conversation_id',
        'conversation_members',
        ['conversation_id']
    )

    # Backfill conversation_members from existing direct conversations
    # For user_one:
    op.execute(
        sa.text(
            """
            INSERT INTO conversation_members (conversation_id, user_id, role, joined_at, last_read_message_id)
            SELECT 
                c.conversation_id,
                c.user_one_id,
                'MEMBER',
                c.created_at,
                (
                    SELECT MAX(m.message_id)
                    FROM messages m
                    WHERE m.conversation_id = c.conversation_id
                      AND (m.sender_id = c.user_one_id OR m.read_at IS NOT NULL)
                )
            FROM conversations c
            WHERE c.user_one_id IS NOT NULL
            ON CONFLICT (conversation_id, user_id) DO NOTHING
            """
        )
    )
    # For user_two:
    op.execute(
        sa.text(
            """
            INSERT INTO conversation_members (conversation_id, user_id, role, joined_at, last_read_message_id)
            SELECT 
                c.conversation_id,
                c.user_two_id,
                'MEMBER',
                c.created_at,
                (
                    SELECT MAX(m.message_id)
                    FROM messages m
                    WHERE m.conversation_id = c.conversation_id
                      AND (m.sender_id = c.user_two_id OR m.read_at IS NOT NULL)
                )
            FROM conversations c
            WHERE c.user_two_id IS NOT NULL
            ON CONFLICT (conversation_id, user_id) DO NOTHING
            """
        )
    )

    # 3. Create conversation_invites table
    op.create_table(
        'conversation_invites',
        sa.Column('invite_id', sa.BigInteger(), sa.Identity(always=False, start=1), nullable=False),
        sa.Column('conversation_id', sa.BigInteger(), nullable=False),
        sa.Column('inviter_id', sa.BigInteger(), nullable=False),
        sa.Column('invitee_id', sa.BigInteger(), nullable=False),
        sa.Column('status', sa.String(length=12), server_default='PENDING', nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('responded_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.conversation_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['inviter_id'], ['users.user_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['invitee_id'], ['users.user_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('invite_id'),
        sa.CheckConstraint("status IN ('PENDING', 'ACCEPTED', 'DECLINED', 'CANCELLED')", name='chk_conversation_invites_status')
    )
    op.create_index(
        'ux_conversation_invites_pending',
        'conversation_invites',
        ['conversation_id', 'invitee_id'],
        unique=True,
        postgresql_where=sa.text("status = 'PENDING'")
    )
    op.create_index(
        'ix_conversation_invites_invitee_status',
        'conversation_invites',
        ['invitee_id', 'status']
    )

    # 4. Update message_attachments kind check constraint
    op.drop_constraint('chk_message_attachments_kind', 'message_attachments', type_='check')
    op.create_check_constraint(
        'chk_message_attachments_kind',
        'message_attachments',
        "kind IN ('IMAGE', 'VIDEO', 'PDF', 'AUDIO', 'DOCUMENT')"
    )


def downgrade() -> None:
    # 1. Revert message_attachments kind check constraint
    op.drop_constraint('chk_message_attachments_kind', 'message_attachments', type_='check')
    op.create_check_constraint(
        'chk_message_attachments_kind',
        'message_attachments',
        "kind IN ('IMAGE', 'VIDEO', 'PDF')"
    )

    # 2. Drop conversation_invites table
    op.drop_index('ix_conversation_invites_invitee_status', table_name='conversation_invites')
    op.drop_index('ux_conversation_invites_pending', table_name='conversation_invites')
    op.drop_table('conversation_invites')

    # 3. Drop conversation_members table
    op.drop_index('ix_conversation_members_conversation_id', table_name='conversation_members')
    op.drop_index('ix_conversation_members_user_active', table_name='conversation_members')
    op.drop_table('conversation_members')

    # 4. Revert conversations table
    op.drop_index('ux_conversations_single_community', table_name='conversations')
    op.drop_index('ux_conversations_direct_pair', table_name='conversations')
    op.drop_constraint('chk_conversations_type', 'conversations', type_='check')

    op.drop_column('conversations', 'direct_pair_key')
    op.drop_column('conversations', 'avatar_url')
    op.drop_column('conversations', 'description')
    op.drop_column('conversations', 'title')
    op.drop_column('conversations', 'type')

    # Re-add legacy constraints (assuming clean test DB)
    op.create_unique_constraint('ux_conversations_participants', 'conversations', ['user_one_id', 'user_two_id'])
    op.create_check_constraint('chk_conversations_user_order', 'conversations', 'user_one_id < user_two_id')
    op.alter_column('conversations', 'user_one_id', nullable=False)
    op.alter_column('conversations', 'user_two_id', nullable=False)
