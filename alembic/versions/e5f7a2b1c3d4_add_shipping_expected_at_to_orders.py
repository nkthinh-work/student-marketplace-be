"""add_shipping_expected_at_to_orders

Revision ID: e5f7a2b1c3d4
Revises: d4e6f8a2b1c3
Create Date: 2026-08-30 22:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5f7a2b1c3d4'
down_revision: Union[str, None] = 'd4e6f8a2b1c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('orders', sa.Column('shipping_expected_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('orders', 'shipping_expected_at')
