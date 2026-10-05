"""create_media_cleanup_jobs_table

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-10-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'media_cleanup_jobs',
        sa.Column('cleanup_id', sa.BigInteger(), sa.Identity(always=False, start=1), nullable=False),
        sa.Column('storage_key', sa.String(length=255), nullable=False),
        sa.Column('resource_type', sa.String(length=20), nullable=False),
        sa.Column('attempt_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('next_retry_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('last_error', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('cleanup_id'),
        sa.UniqueConstraint('storage_key', 'resource_type', name='uq_media_cleanup_jobs_key_type'),
    )
    op.create_index(
        'ix_media_cleanup_jobs_next_retry',
        'media_cleanup_jobs',
        ['next_retry_at', 'cleanup_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_media_cleanup_jobs_next_retry', table_name='media_cleanup_jobs')
    op.drop_table('media_cleanup_jobs')
