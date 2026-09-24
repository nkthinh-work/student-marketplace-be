"""create_message_attachments_table

Revision ID: 7a1b2c3d4e5f
Revises: ff6a57a76040
Create Date: 2026-09-02 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7a1b2c3d4e5f'
down_revision: Union[str, None] = 'ff6a57a76040'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Drop chk_messages_type_content so messages with attachments can have NULL content
    op.drop_constraint('chk_messages_type_content', 'messages', type_='check')

    # 2. Create message_attachments table
    op.create_table(
        'message_attachments',
        sa.Column('attachment_id', sa.BigInteger(), sa.Identity(always=False, start=1), nullable=False),
        sa.Column('message_id', sa.BigInteger(), nullable=False),
        sa.Column('kind', sa.String(length=10), nullable=False),
        sa.Column('url', sa.Text(), nullable=False),
        sa.Column('storage_key', sa.String(length=255), nullable=False),
        sa.Column('mime_type', sa.String(length=100), nullable=False),
        sa.Column('original_name', sa.String(length=255), nullable=False),
        sa.Column('size_bytes', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("kind IN ('IMAGE', 'VIDEO', 'PDF')", name='chk_message_attachments_kind'),
        sa.ForeignKeyConstraint(['message_id'], ['messages.message_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('attachment_id'),
    )

    # 3. Create index on message_id
    op.create_index(
        'ix_message_attachments_message_id',
        'message_attachments',
        ['message_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_message_attachments_message_id', table_name='message_attachments')
    op.drop_table('message_attachments')

    op.create_check_constraint(
        'chk_messages_type_content',
        'messages',
        "type <> 'TEXT' OR content IS NOT NULL",
    )
