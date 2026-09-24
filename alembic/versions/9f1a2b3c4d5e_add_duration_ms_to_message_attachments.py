"""add_duration_ms_to_message_attachments

Revision ID: 9f1a2b3c4d5e
Revises: 8c3d4e5f6a7b
Create Date: 2026-09-02 23:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9f1a2b3c4d5e'
down_revision: Union[str, None] = '8c3d4e5f6a7b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'message_attachments',
        sa.Column('duration_ms', sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('message_attachments', 'duration_ms')
