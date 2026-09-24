"""group_approval_settings_and_system_messages

Revision ID: e58355f24d58
Revises: e8a9b1c2d3e4
Create Date: 2026-09-05 18:16:59.753256

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e58355f24d58'
down_revision: Union[str, None] = 'e8a9b1c2d3e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add requires_approval column to conversations
    op.add_column(
        "conversations",
        sa.Column(
            "requires_approval",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )

    # 2. Expand status column length in conversation_invites from 12 to 20
    op.alter_column(
        "conversation_invites",
        "status",
        type_=sa.String(length=20),
        existing_type=sa.String(length=12),
        existing_nullable=False,
        existing_server_default="PENDING",
    )

    # 3. Update check constraint on conversation_invites
    op.drop_constraint("chk_conversation_invites_status", "conversation_invites", type_="check")
    op.create_check_constraint(
        "chk_conversation_invites_status",
        "conversation_invites",
        "status IN ('PENDING', 'PENDING_APPROVAL', 'ACCEPTED', 'DECLINED', 'CANCELLED')",
    )

    # 4. Update partial unique index to cover PENDING and PENDING_APPROVAL
    op.drop_index("ux_conversation_invites_pending", table_name="conversation_invites")
    op.create_index(
        "ux_conversation_invites_pending",
        "conversation_invites",
        ["conversation_id", "invitee_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('PENDING', 'PENDING_APPROVAL')"),
    )


def downgrade() -> None:
    # 1. Drop the updated partial unique index
    op.drop_index("ux_conversation_invites_pending", table_name="conversation_invites")

    # 2. Normalize any PENDING_APPROVAL status:
    # Cancel duplicates if a PENDING invite already exists for the same pair
    op.execute(
        """
        UPDATE conversation_invites ci
        SET status = 'CANCELLED'
        WHERE ci.status = 'PENDING_APPROVAL'
          AND EXISTS (
              SELECT 1 FROM conversation_invites other
              WHERE other.conversation_id = ci.conversation_id
                AND other.invitee_id = ci.invitee_id
                AND other.status = 'PENDING'
                AND other.invite_id != ci.invite_id
          )
        """
    )
    # Remaining PENDING_APPROVAL become PENDING
    op.execute("UPDATE conversation_invites SET status = 'PENDING' WHERE status = 'PENDING_APPROVAL'")

    # 3. Restore old partial unique index
    op.create_index(
        "ux_conversation_invites_pending",
        "conversation_invites",
        ["conversation_id", "invitee_id"],
        unique=True,
        postgresql_where=sa.text("status = 'PENDING'"),
    )

    # 4. Restore old check constraint
    op.drop_constraint("chk_conversation_invites_status", "conversation_invites", type_="check")
    op.create_check_constraint(
        "chk_conversation_invites_status",
        "conversation_invites",
        "status IN ('PENDING', 'ACCEPTED', 'DECLINED', 'CANCELLED')",
    )

    # 5. Restore column length to 12
    op.alter_column(
        "conversation_invites",
        "status",
        type_=sa.String(length=12),
        existing_type=sa.String(length=20),
        existing_nullable=False,
        existing_server_default="PENDING",
    )

    # 6. Drop requires_approval column from conversations
    op.drop_column("conversations", "requires_approval")
