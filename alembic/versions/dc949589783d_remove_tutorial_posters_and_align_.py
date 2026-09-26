"""remove_tutorial_posters_and_align_navigation

Revision ID: dc949589783d
Revises: 1b009a1b9a9f
Create Date: 2026-09-25 12:26:13.989496

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dc949589783d'
down_revision: Union[str, None] = '1b009a1b9a9f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Map legacy feature_keys to navigation-aligned keys
    op.execute(
        sa.text(
            "UPDATE tutorials SET feature_key = 'PROFILE' WHERE feature_key = 'ACCOUNT';"
        )
    )
    op.execute(
        sa.text(
            "UPDATE tutorials SET feature_key = 'CREATE_PRODUCT' WHERE feature_key = 'PRODUCTS';"
        )
    )
    op.execute(
        sa.text(
            "UPDATE tutorials SET feature_key = 'HOME' WHERE feature_key = 'GETTING_STARTED';"
        )
    )
    op.execute(
        sa.text(
            "UPDATE tutorials SET feature_key = 'BUYER_ORDERS' WHERE feature_key = 'ORDERS';"
        )
    )

    # 2. Drop poster check constraint
    op.drop_constraint('chk_tutorials_poster_all_or_none', 'tutorials', type_='check')

    # 3. Drop poster columns
    op.drop_column('tutorials', 'poster_mime_type')
    op.drop_column('tutorials', 'poster_storage_key')
    op.drop_column('tutorials', 'poster_url')


def downgrade() -> None:
    # 1. Recreate poster columns as nullable
    op.add_column('tutorials', sa.Column('poster_url', sa.String(500), nullable=True))
    op.add_column('tutorials', sa.Column('poster_storage_key', sa.String(255), nullable=True))
    op.add_column('tutorials', sa.Column('poster_mime_type', sa.String(50), nullable=True))

    # 2. Recreate check constraint
    op.create_check_constraint(
        'chk_tutorials_poster_all_or_none',
        'tutorials',
        "((poster_url IS NULL) AND (poster_storage_key IS NULL) AND (poster_mime_type IS NULL)) OR "
        "((poster_url IS NOT NULL) AND (poster_storage_key IS NOT NULL) AND (poster_mime_type IS NOT NULL))",
    )

    # 3. Revert feature_keys best-effort
    op.execute(
        sa.text(
            "UPDATE tutorials SET feature_key = 'ACCOUNT' WHERE feature_key = 'PROFILE';"
        )
    )
    op.execute(
        sa.text(
            "UPDATE tutorials SET feature_key = 'PRODUCTS' WHERE feature_key = 'CREATE_PRODUCT';"
        )
    )
