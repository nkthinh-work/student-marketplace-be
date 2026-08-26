"""create categories products product images

Revision ID: 3d2ea1176b6a
Revises: 510df5f4f2be
Create Date: 2026-08-26 15:40:26.538373

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3d2ea1176b6a'
down_revision: Union[str, None] = '510df5f4f2be'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create categories table
    op.create_table(
        'categories',
        sa.Column('category_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('slug', sa.String(length=120), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('FALSE'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.PrimaryKeyConstraint('category_id', name='pk_categories')
    )
    op.create_index(
        'ux_categories_slug',
        'categories',
        ['slug'],
        unique=True,
        postgresql_where=sa.text('is_deleted = FALSE')
    )

    # 2. Create products table
    op.create_table(
        'products',
        sa.Column('product_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('seller_id', sa.BigInteger(), nullable=False),
        sa.Column('category_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('item_condition', sa.String(length=10), nullable=False),
        sa.Column('listing_type', sa.String(length=12), server_default='FIXED_PRICE', nullable=False),
        sa.Column('price', sa.Numeric(precision=12, scale=0), nullable=False),
        sa.Column('stock', sa.Integer(), server_default='1', nullable=False),
        sa.Column('reserved_stock', sa.Integer(), server_default='0', nullable=False),
        sa.Column('status', sa.String(length=10), server_default='AVAILABLE', nullable=False),
        sa.Column('view_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('FALSE'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.CheckConstraint('price >= 0', name='chk_products_price'),
        sa.CheckConstraint('stock >= 0', name='chk_products_stock'),
        sa.CheckConstraint('reserved_stock >= 0 AND reserved_stock <= stock', name='chk_products_reserved_stock'),
        sa.CheckConstraint("item_condition IN ('NEW_99', 'USED_GOOD', 'USED_FAIR')", name='chk_products_item_condition'),
        sa.CheckConstraint("listing_type IN ('FIXED_PRICE', 'AUCTION')", name='chk_products_listing_type'),
        sa.CheckConstraint("status IN ('AVAILABLE', 'HIDDEN', 'SOLD_OUT')", name='chk_products_status'),
        sa.ForeignKeyConstraint(['category_id'], ['categories.category_id'], name='fk_products_categories', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['seller_id'], ['users.user_id'], name='fk_products_users', ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('product_id', name='pk_products')
    )
    op.create_index(
        'ix_products_category_status',
        'products',
        ['category_id', 'status', 'is_deleted', 'created_at']
    )
    op.create_index(
        'ix_products_seller_status',
        'products',
        ['seller_id', 'status', 'created_at']
    )
    op.create_index(
        'ix_products_listing_type_status',
        'products',
        ['listing_type', 'status', 'is_deleted', 'created_at']
    )
    # GIN Full-text index on products(title, description)
    op.execute(
        "CREATE INDEX ix_products_search_gin ON products "
        "USING gin (to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(description, '')))"
    )

    # 3. Create product_images table
    op.create_table(
        'product_images',
        sa.Column('image_id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('product_id', sa.BigInteger(), nullable=False),
        sa.Column('image_url', sa.String(length=500), nullable=False),
        sa.Column('sort_order', sa.SmallInteger(), server_default='0', nullable=False),
        sa.Column('is_thumbnail', sa.Boolean(), server_default=sa.text('FALSE'), nullable=False),
        sa.ForeignKeyConstraint(['product_id'], ['products.product_id'], name='fk_product_images_products', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('image_id', name='pk_product_images'),
        sa.UniqueConstraint('product_id', 'image_url', name='ux_product_images_product_url')
    )
    op.create_index(
        'ux_product_images_thumbnail',
        'product_images',
        ['product_id'],
        unique=True,
        postgresql_where=sa.text('is_thumbnail = TRUE')
    )
    op.create_index(
        'ix_product_images_product_sort',
        'product_images',
        ['product_id', 'sort_order', 'image_id']
    )


def downgrade() -> None:
    op.drop_index('ix_product_images_product_sort', table_name='product_images')
    op.drop_index('ux_product_images_thumbnail', table_name='product_images')
    op.drop_table('product_images')

    op.execute('DROP INDEX IF EXISTS ix_products_search_gin')
    op.drop_index('ix_products_listing_type_status', table_name='products')
    op.drop_index('ix_products_seller_status', table_name='products')
    op.drop_index('ix_products_category_status', table_name='products')
    op.drop_table('products')

    op.drop_index('ux_categories_slug', table_name='categories')
    op.drop_table('categories')
