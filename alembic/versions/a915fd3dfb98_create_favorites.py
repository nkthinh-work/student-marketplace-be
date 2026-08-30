"""create_favorites

Revision ID: a915fd3dfb98
Revises: 8b242495fd1d
Create Date: 2026-08-29 17:26:36.653655

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a915fd3dfb98'
down_revision: Union[str, None] = '8b242495fd1d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "favorites",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("user_id", "product_id"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.user_id"],
            name="fk_favorites_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.product_id"],
            name="fk_favorites_products",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_favorites_product_id", "favorites", ["product_id"])


def downgrade() -> None:
    op.drop_index("ix_favorites_product_id", table_name="favorites")
    op.drop_table("favorites")
