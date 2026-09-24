"""add_community_moment_note_and_site_feedback

Revision ID: baf84a486cb8
Revises: 41154769d8c9
Create Date: 2026-09-21 15:18:45.685638

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'baf84a486cb8'
down_revision: Union[str, None] = '41154769d8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add nullable note to community_moments (legacy rows remain NULL, new submissions validate in app)
    op.add_column('community_moments', sa.Column('note', sa.String(length=80), nullable=True))

    # 2. Create site_feedback table
    op.create_table(
        'site_feedback',
        sa.Column('feedback_id', sa.BigInteger(), sa.Identity(always=False, start=1), nullable=False),
        sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.user_id', ondelete='RESTRICT'), nullable=False),
        sa.Column('rating', sa.SmallInteger(), nullable=False),
        sa.Column('content', sa.String(length=300), nullable=False),
        sa.Column('status', sa.String(length=20), server_default='PENDING', nullable=False),
        sa.Column('is_featured', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('featured_at', sa.DateTime(), nullable=True),
        sa.Column('reviewed_by', sa.BigInteger(), sa.ForeignKey('users.user_id', ondelete='SET NULL'), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('feedback_id'),
        sa.UniqueConstraint('user_id', name='uq_site_feedback_user_id'),
        sa.CheckConstraint('rating >= 1 AND rating <= 5', name='chk_site_feedback_rating'),
        sa.CheckConstraint("status IN ('PENDING', 'APPROVED', 'REJECTED')", name='chk_site_feedback_status'),
    )

    op.create_index(
        'idx_site_feedback_admin_status_updated',
        'site_feedback',
        ['status', 'updated_at', 'feedback_id'],
    )
    op.create_index(
        'idx_site_feedback_featured',
        'site_feedback',
        ['featured_at', 'feedback_id'],
        postgresql_where=sa.text("status = 'APPROVED' AND is_featured = true"),
    )


def downgrade() -> None:
    op.drop_index('idx_site_feedback_featured', table_name='site_feedback')
    op.drop_index('idx_site_feedback_admin_status_updated', table_name='site_feedback')
    op.drop_table('site_feedback')
    op.drop_column('community_moments', 'note')
