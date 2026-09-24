"""create_reviews_table

Revision ID: 0b6255d0ebcd
Revises: b2c3d4e5f6a7
Create Date: 2026-09-01 16:43:05.974952

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0b6255d0ebcd'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create reviews table
    op.create_table(
        'reviews',
        sa.Column('review_id', sa.BigInteger(), sa.Identity(always=False, start=1), nullable=False),
        sa.Column('order_id', sa.BigInteger(), nullable=False),
        sa.Column('reviewer_id', sa.BigInteger(), nullable=False),
        sa.Column('reviewee_id', sa.BigInteger(), nullable=False),
        sa.Column('rating', sa.SmallInteger(), nullable=False),
        sa.Column('comment', sa.String(length=1000), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('rating >= 1 AND rating <= 5', name='chk_reviews_rating'),
        sa.CheckConstraint('reviewer_id <> reviewee_id', name='chk_reviews_reviewer_not_reviewee'),
        sa.ForeignKeyConstraint(['order_id'], ['orders.order_id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['reviewer_id'], ['users.user_id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['reviewee_id'], ['users.user_id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('review_id'),
        sa.UniqueConstraint('order_id', 'reviewer_id', name='ux_reviews_order_reviewer'),
    )

    # 2. Keyset pagination index (reviewee_id, created_at DESC, review_id DESC)
    op.create_index(
        'ix_reviews_reviewee_created_desc',
        'reviews',
        ['reviewee_id', sa.text('created_at DESC'), sa.text('review_id DESC')],
        unique=False,
    )

    # 3. updated_at trigger
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_reviews_updated_at ON reviews;"))
    op.execute(sa.text("""
        CREATE TRIGGER trg_reviews_updated_at
        BEFORE UPDATE ON reviews
        FOR EACH ROW
        EXECUTE FUNCTION update_updated_at_column();
    """))


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_reviews_updated_at ON reviews;"))
    op.drop_index('ix_reviews_reviewee_created_desc', table_name='reviews')
    op.drop_table('reviews')
