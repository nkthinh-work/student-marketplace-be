"""phase7c mentions and group soft delete

Revision ID: e8a9b1c2d3e4
Revises: cc8aeddfcb89
Create Date: 2026-09-04 12:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e8a9b1c2d3e4"
down_revision: Union[str, None] = "cc8aeddfcb89"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add deleted_at to conversations
    op.add_column(
        "conversations",
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_conversations_deleted_at",
        "conversations",
        ["deleted_at"],
    )

    # 2. Create message_mentions table
    op.create_table(
        "message_mentions",
        sa.Column("mention_id", sa.BigInteger(), sa.Identity(always=False, start=1), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("mentioned_user_id", sa.BigInteger(), nullable=False),
        sa.Column("display_text", sa.String(length=100), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["messages.message_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["mentioned_user_id"],
            ["users.user_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("mention_id"),
        sa.UniqueConstraint("message_id", "mentioned_user_id", name="uq_message_mentions_msg_user"),
    )
    op.create_index(
        "ix_message_mentions_user_id",
        "message_mentions",
        ["mentioned_user_id"],
    )
    op.create_index(
        "ix_message_mentions_message_id",
        "message_mentions",
        ["message_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_message_mentions_message_id", table_name="message_mentions")
    op.drop_index("ix_message_mentions_user_id", table_name="message_mentions")
    op.drop_table("message_mentions")

    op.drop_index("ix_conversations_deleted_at", table_name="conversations")
    op.drop_column("conversations", "deleted_at")
