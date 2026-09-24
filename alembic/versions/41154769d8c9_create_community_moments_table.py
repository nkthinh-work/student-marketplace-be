"""create_community_moments_table

Revision ID: 41154769d8c9
Revises: 820160377ff1
Create Date: 2026-09-21 14:39:57.810512

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '41154769d8c9'
down_revision: Union[str, None] = '820160377ff1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'community_moments',
        sa.Column('moment_id', sa.BigInteger(), sa.Identity(always=False, start=1), nullable=False),
        sa.Column('uploader_id', sa.BigInteger(), sa.ForeignKey('users.user_id', ondelete='RESTRICT'), nullable=False),
        sa.Column('image_url', sa.String(length=500), nullable=False),
        sa.Column('storage_key', sa.String(length=255), nullable=False),
        sa.Column('mime_type', sa.String(length=100), nullable=False),
        sa.Column('size_bytes', sa.BigInteger(), nullable=False),
        sa.Column('status', sa.String(length=20), server_default='PENDING', nullable=False),
        sa.Column('reviewed_by', sa.BigInteger(), sa.ForeignKey('users.user_id', ondelete='SET NULL'), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('moment_id'),
        sa.CheckConstraint("status IN ('PENDING', 'APPROVED', 'REJECTED')", name='chk_community_moments_status'),
        sa.CheckConstraint('size_bytes > 0', name='chk_community_moments_size_bytes'),
    )

    op.create_index(
        'uq_community_moments_user_pending',
        'community_moments',
        ['uploader_id'],
        unique=True,
        postgresql_where=sa.text("status = 'PENDING'"),
    )
    op.create_index(
        'ix_community_moments_status_created',
        'community_moments',
        ['status', 'created_at', 'moment_id'],
    )
    op.create_index(
        'ix_community_moments_approved_hero',
        'community_moments',
        ['status', 'reviewed_at', 'moment_id'],
    )


def downgrade() -> None:
    op.drop_index('ix_community_moments_approved_hero', table_name='community_moments')
    op.drop_index('ix_community_moments_status_created', table_name='community_moments')
    op.drop_index('uq_community_moments_user_pending', table_name='community_moments')
    op.drop_table('community_moments')
