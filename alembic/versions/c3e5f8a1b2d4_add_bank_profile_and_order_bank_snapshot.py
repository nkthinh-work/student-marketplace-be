"""add_bank_profile_and_order_bank_snapshot

Revision ID: c3e5f8a1b2d4
Revises: b1c4e7f9a2d3
Create Date: 2026-08-30 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3e5f8a1b2d4'
down_revision: Union[str, None] = 'b1c4e7f9a2d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add bank profile columns to users
    op.add_column('users', sa.Column('bank_bin', sa.String(length=10), nullable=True))
    op.add_column('users', sa.Column('bank_account_number', sa.String(length=30), nullable=True))
    op.add_column('users', sa.Column('bank_account_name', sa.String(length=100), nullable=True))

    # 2. Add payment bank snapshot columns to orders
    op.add_column('orders', sa.Column('payment_bank_bin', sa.String(length=10), nullable=True))
    op.add_column('orders', sa.Column('payment_bank_account_number', sa.String(length=30), nullable=True))
    op.add_column('orders', sa.Column('payment_bank_account_name', sa.String(length=100), nullable=True))


def downgrade() -> None:
    # 1. Drop payment bank snapshot columns from orders
    op.drop_column('orders', 'payment_bank_account_name')
    op.drop_column('orders', 'payment_bank_account_number')
    op.drop_column('orders', 'payment_bank_bin')

    # 2. Drop bank profile columns from users
    op.drop_column('users', 'bank_account_name')
    op.drop_column('users', 'bank_account_number')
    op.drop_column('users', 'bank_bin')
