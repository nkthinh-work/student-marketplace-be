"""add_public_id_to_users

Revision ID: a7b8c9d0e1f2
Revises: f1a2b3c4d5e6
Create Date: 2026-10-03 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add nullable public_id column
    op.add_column(
        'users',
        sa.Column('public_id', postgresql.UUID(as_uuid=True), nullable=True)
    )

    # 2. Backfill every existing user with cryptographically random UUID v4
    op.execute(sa.text("UPDATE users SET public_id = gen_random_uuid() WHERE public_id IS NULL"))

    # 3. Configure default for future records and enforce NOT NULL
    op.alter_column(
        'users',
        'public_id',
        nullable=False,
        server_default=sa.text('gen_random_uuid()')
    )

    # 4. Add UNIQUE constraint (creates unique index ux_users_public_id in PostgreSQL)
    op.create_unique_constraint('ux_users_public_id', 'users', ['public_id'])


def downgrade() -> None:
    op.drop_constraint('ux_users_public_id', 'users', type_='unique')
    op.drop_column('users', 'public_id')
