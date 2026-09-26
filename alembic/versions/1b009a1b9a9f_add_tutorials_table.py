"""add_tutorials_table

Revision ID: 1b009a1b9a9f
Revises: 36b9d7d15f56
Create Date: 2026-09-25 16:00:59.763491

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1b009a1b9a9f'
down_revision: Union[str, None] = '36b9d7d15f56'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'tutorials',
        sa.Column('tutorial_id', sa.BigInteger(), sa.Identity(always=False, start=1), nullable=False),
        sa.Column('feature_key', sa.String(length=40), nullable=False),
        sa.Column('title', sa.String(length=120), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('video_url', sa.String(length=500), nullable=False),
        sa.Column('video_storage_key', sa.String(length=255), nullable=False),
        sa.Column('video_mime_type', sa.String(length=50), nullable=False),
        sa.Column('video_size_bytes', sa.BigInteger(), nullable=False),
        sa.Column('duration_ms', sa.BigInteger(), nullable=True),
        sa.Column('poster_url', sa.String(length=500), nullable=True),
        sa.Column('poster_storage_key', sa.String(length=255), nullable=True),
        sa.Column('poster_mime_type', sa.String(length=50), nullable=True),
        sa.Column('action_key', sa.String(length=50), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('is_published', sa.Boolean(), server_default=sa.text('FALSE'), nullable=False),
        sa.Column('created_by', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.CheckConstraint('video_size_bytes > 0', name='chk_tutorials_video_size_pos'),
        sa.CheckConstraint('duration_ms IS NULL OR duration_ms > 0', name='chk_tutorials_duration_pos'),
        sa.CheckConstraint('sort_order >= 0', name='chk_tutorials_sort_order_nonneg'),
        sa.CheckConstraint(
            '((poster_url IS NULL) AND (poster_storage_key IS NULL) AND (poster_mime_type IS NULL)) OR '
            '((poster_url IS NOT NULL) AND (poster_storage_key IS NOT NULL) AND (poster_mime_type IS NOT NULL))',
            name='chk_tutorials_poster_all_or_none',
        ),
        sa.ForeignKeyConstraint(['created_by'], ['users.user_id'], ondelete='RESTRICT', name='fk_tutorials_created_by'),
        sa.PrimaryKeyConstraint('tutorial_id', name='pk_tutorials'),
    )
    op.create_index(
        'ix_tutorials_pub_feature_sort',
        'tutorials',
        ['is_published', 'feature_key', 'sort_order', 'tutorial_id'],
    )
    op.create_index(
        'ix_tutorials_created_by',
        'tutorials',
        ['created_by'],
    )

    # updated_at trigger for tutorials table
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_tutorials_updated_at ON tutorials;"))
    op.execute(
        sa.text(
            """
        CREATE TRIGGER trg_tutorials_updated_at
        BEFORE UPDATE ON tutorials
        FOR EACH ROW
        EXECUTE FUNCTION update_updated_at_column();
        """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_tutorials_updated_at ON tutorials;"))
    op.drop_index('ix_tutorials_created_by', table_name='tutorials')
    op.drop_index('ix_tutorials_pub_feature_sort', table_name='tutorials')
    op.drop_table('tutorials')
