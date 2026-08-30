"""add delivery_area to users

Revision ID: f6a8b2c4d1e3
Revises: e5f7a2b1c3d4
Create Date: 2026-08-30 23:22:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6a8b2c4d1e3'
down_revision: Union[str, None] = 'e5f7a2b1c3d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('delivery_area', sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'delivery_area')
