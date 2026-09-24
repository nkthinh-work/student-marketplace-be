"""feedback_redesign_issue_and_attachments

Revision ID: eeb83ca4d13e
Revises: baf84a486cb8
Create Date: 2026-09-21 22:32:47.528606

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'eeb83ca4d13e'
down_revision: Union[str, None] = 'baf84a486cb8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Drop old moderation, rating, and featured indexes from site_feedback
    op.drop_index('idx_site_feedback_featured', table_name='site_feedback')
    op.drop_index('idx_site_feedback_admin_status_updated', table_name='site_feedback')

    # 2. Drop old check constraints and unique constraint
    op.drop_constraint('chk_site_feedback_rating', 'site_feedback', type_='check')
    op.drop_constraint('chk_site_feedback_status', 'site_feedback', type_='check')
    op.drop_constraint('uq_site_feedback_user_id', 'site_feedback', type_='unique')

    # 3. Update FK on user_id to ON DELETE CASCADE
    op.drop_constraint('site_feedback_user_id_fkey', 'site_feedback', type_='foreignkey')
    op.create_foreign_key(
        'site_feedback_user_id_fkey',
        'site_feedback',
        'users',
        ['user_id'],
        ['user_id'],
        ondelete='CASCADE',
    )

    # 4. Drop obsolete columns from site_feedback
    op.drop_column('site_feedback', 'rating')
    op.drop_column('site_feedback', 'status')
    op.drop_column('site_feedback', 'is_featured')
    op.drop_column('site_feedback', 'featured_at')
    op.drop_column('site_feedback', 'reviewed_by')
    op.drop_column('site_feedback', 'reviewed_at')

    # 5. Widen content column from 300 to 500 characters
    op.alter_column(
        'site_feedback',
        'content',
        existing_type=sa.String(length=300),
        type_=sa.String(length=500),
        nullable=False,
    )

    # 6. Create new indexes on site_feedback
    op.create_index(
        'idx_site_feedback_created_at',
        'site_feedback',
        [sa.text('created_at DESC'), sa.text('feedback_id DESC')],
    )
    op.create_index(
        'idx_site_feedback_user_created',
        'site_feedback',
        ['user_id', sa.text('created_at DESC'), sa.text('feedback_id DESC')],
    )

    # 7. Create site_feedback_attachments table
    op.create_table(
        'site_feedback_attachments',
        sa.Column('attachment_id', sa.BigInteger(), sa.Identity(always=False, start=1), nullable=False),
        sa.Column('feedback_id', sa.BigInteger(), sa.ForeignKey('site_feedback.feedback_id', ondelete='CASCADE'), nullable=False),
        sa.Column('kind', sa.String(length=10), nullable=False),
        sa.Column('media_url', sa.String(length=500), nullable=False),
        sa.Column('storage_key', sa.String(length=255), nullable=False),
        sa.Column('mime_type', sa.String(length=50), nullable=False),
        sa.Column('size_bytes', sa.BigInteger(), nullable=False),
        sa.Column('duration_ms', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('attachment_id'),
        sa.CheckConstraint("kind IN ('IMAGE', 'VIDEO')", name='chk_site_feedback_attachments_kind'),
        sa.CheckConstraint('size_bytes > 0', name='chk_site_feedback_attachments_size_bytes'),
    )
    op.create_index('idx_site_feedback_attachments_feedback_id', 'site_feedback_attachments', ['feedback_id'])


def downgrade() -> None:
    # 1. Drop site_feedback_attachments table
    op.drop_index('idx_site_feedback_attachments_feedback_id', table_name='site_feedback_attachments')
    op.drop_table('site_feedback_attachments')

    # 2. Drop new indexes on site_feedback
    op.drop_index('idx_site_feedback_user_created', table_name='site_feedback')
    op.drop_index('idx_site_feedback_created_at', table_name='site_feedback')

    # 3. Alter content back to VARCHAR(300)
    op.alter_column(
        'site_feedback',
        'content',
        existing_type=sa.String(length=500),
        type_=sa.String(length=300),
        nullable=False,
    )

    # 4. Add old columns back to site_feedback
    op.add_column('site_feedback', sa.Column('rating', sa.SmallInteger(), server_default='5', nullable=False))
    op.add_column('site_feedback', sa.Column('status', sa.String(length=20), server_default='PENDING', nullable=False))
    op.add_column('site_feedback', sa.Column('is_featured', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('site_feedback', sa.Column('featured_at', sa.DateTime(), nullable=True))
    op.add_column('site_feedback', sa.Column('reviewed_by', sa.BigInteger(), sa.ForeignKey('users.user_id', ondelete='SET NULL'), nullable=True))
    op.add_column('site_feedback', sa.Column('reviewed_at', sa.DateTime(), nullable=True))

    # 5. Restore FK on user_id to ON DELETE RESTRICT
    op.drop_constraint('site_feedback_user_id_fkey', 'site_feedback', type_='foreignkey')
    op.create_foreign_key(
        'site_feedback_user_id_fkey',
        'site_feedback',
        'users',
        ['user_id'],
        ['user_id'],
        ondelete='RESTRICT',
    )

    # 6. Add constraints back
    op.create_unique_constraint('uq_site_feedback_user_id', 'site_feedback', ['user_id'])
    op.create_check_constraint('chk_site_feedback_rating', 'site_feedback', 'rating >= 1 AND rating <= 5')
    op.create_check_constraint("chk_site_feedback_status", "site_feedback", "status IN ('PENDING', 'APPROVED', 'REJECTED')")

    # 7. Add indexes back
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
