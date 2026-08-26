"""remove_products_item_condition

Revision ID: 8b242495fd1d
Revises: 3d2ea1176b6a
Create Date: 2026-08-26 20:43:43.184038

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8b242495fd1d'
down_revision: Union[str, None] = '3d2ea1176b6a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Drop check constraint on item_condition
    op.drop_constraint('chk_products_item_condition', 'products', type_='check')

    # 2. Drop item_condition column from products
    op.drop_column('products', 'item_condition')


def downgrade() -> None:
    # Note: Downgrade restores the schema structure and check constraint.
    # Because upgrade dropped the original item_condition values, downgrade
    # cannot recover historical condition data and uses 'USED_GOOD' as a
    # temporary backfill before removing the default.

    # 1. Add column item_condition as nullable with temporary default
    op.add_column(
        'products',
        sa.Column('item_condition', sa.String(length=10), nullable=True, server_default='USED_GOOD')
    )

    # 2. Backfill any existing rows
    op.execute("UPDATE products SET item_condition = 'USED_GOOD' WHERE item_condition IS NULL")

    # 3. Alter column to NOT NULL
    op.alter_column('products', 'item_condition', nullable=False)

    # 4. Remove temporary server_default to match original DB_v7 schema (no permanent default)
    op.alter_column('products', 'item_condition', server_default=None)

    # 5. Recreate check constraint
    op.create_check_constraint(
        'chk_products_item_condition',
        'products',
        "item_condition IN ('NEW_99', 'USED_GOOD', 'USED_FAIR')"
    )
