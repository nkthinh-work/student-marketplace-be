"""add_nickname_to_conversation_members

Revision ID: 84ca2057bbd1
Revises: 0ec5c6081b6d
Create Date: 2026-09-15 09:35:16.441503

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '84ca2057bbd1'
down_revision: Union[str, None] = '0ec5c6081b6d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'conversation_members',
        sa.Column('nickname', sa.String(length=40), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('conversation_members', 'nickname')
