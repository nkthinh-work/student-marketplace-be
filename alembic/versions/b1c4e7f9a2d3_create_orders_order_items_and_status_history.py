"""create_orders_order_items_and_status_history

Revision ID: b1c4e7f9a2d3
Revises: a915fd3dfb98
Create Date: 2026-08-29 18:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b1c4e7f9a2d3'
down_revision: Union[str, None] = 'a915fd3dfb98'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create payment_status_t enum type safely using DO block
    op.execute(sa.text("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'payment_status_t') THEN
                CREATE TYPE payment_status_t AS ENUM ('UNPAID', 'VERIFYING', 'PAID');
            END IF;
        END $$;
    """))

    payment_status_enum = postgresql.ENUM(
        'UNPAID', 'VERIFYING', 'PAID', name='payment_status_t', create_type=False
    )

    # 2. Create orders table
    op.create_table(
        'orders',
        sa.Column('order_id', sa.BigInteger(), sa.Identity(always=False, start=1), nullable=False),
        sa.Column('order_code', sa.String(length=20), nullable=False),
        sa.Column('buyer_id', sa.BigInteger(), nullable=False),
        sa.Column('seller_id', sa.BigInteger(), nullable=False),
        sa.Column('status', sa.String(length=12), server_default='PENDING', nullable=False),
        sa.Column('payment_method', sa.String(length=20), server_default='CASH_ON_MEETUP', nullable=False),
        sa.Column('payment_status', payment_status_enum, server_default='UNPAID', nullable=False),
        sa.Column('payment_receipt_url', sa.String(length=500), nullable=True),
        sa.Column('receipt_uploaded_at', sa.DateTime(), nullable=True),
        sa.Column('paid_confirmed_at', sa.DateTime(), nullable=True),
        sa.Column('payment_note', sa.String(length=255), nullable=True),
        sa.Column('fulfillment_method', sa.String(length=10), server_default='MEETUP', nullable=False),
        sa.Column('meetup_place', sa.String(length=255), nullable=True),
        sa.Column('meetup_time', sa.DateTime(), nullable=True),
        sa.Column('shipping_address', sa.String(length=500), nullable=True),
        sa.Column('contact_name', sa.String(length=100), nullable=False),
        sa.Column('contact_phone', sa.String(length=20), nullable=False),
        sa.Column('buyer_note', sa.String(length=500), nullable=True),
        sa.Column('total_amount', sa.Numeric(precision=12, scale=0), nullable=False),
        sa.Column('auto_cancel_at', sa.DateTime(), nullable=True),
        sa.Column('confirmed_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(), nullable=True),
        sa.Column('cancelled_by', sa.String(length=10), nullable=True),
        sa.Column('cancel_reason', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.PrimaryKeyConstraint('order_id', name='pk_orders'),
        sa.UniqueConstraint('order_code', name='ux_orders_order_code'),
        sa.ForeignKeyConstraint(['buyer_id'], ['users.user_id'], name='fk_orders_buyer_users', ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['seller_id'], ['users.user_id'], name='fk_orders_seller_users', ondelete='RESTRICT'),
        sa.CheckConstraint('buyer_id <> seller_id', name='chk_orders_buyer_not_seller'),
        sa.CheckConstraint("status IN ('PENDING', 'CONFIRMED', 'DELIVERING', 'COMPLETED', 'CANCELLED')", name='chk_orders_status'),
        sa.CheckConstraint("payment_method IN ('CASH_ON_MEETUP', 'BANK_TRANSFER', 'OTHER')", name='chk_orders_payment_method'),
        sa.CheckConstraint("fulfillment_method IN ('MEETUP', 'SHIPPING')", name='chk_orders_fulfillment_method'),
        sa.CheckConstraint("cancelled_by IS NULL OR cancelled_by IN ('BUYER', 'SELLER', 'SYSTEM')", name='chk_orders_cancelled_by'),
        sa.CheckConstraint("payment_status <> 'VERIFYING' OR payment_receipt_url IS NOT NULL", name='chk_orders_verifying_receipt'),
        sa.CheckConstraint("payment_status <> 'PAID' OR paid_confirmed_at IS NOT NULL", name='chk_orders_paid_confirmed'),
    )

    op.create_index('ix_orders_buyer_status_created', 'orders', ['buyer_id', 'status', 'created_at'])
    op.create_index('ix_orders_seller_status_created', 'orders', ['seller_id', 'status', 'created_at'])
    op.create_index('ix_orders_status_paystatus_autocancel', 'orders', ['status', 'payment_status', 'auto_cancel_at'])
    op.create_index('ix_orders_paystatus_receipt_uploaded', 'orders', ['payment_status', 'receipt_uploaded_at'])

    # updated_at trigger for orders table
    op.execute(sa.text("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'update_updated_at_column') THEN
                CREATE FUNCTION update_updated_at_column()
                RETURNS TRIGGER AS $func$
                BEGIN
                    NEW.updated_at = NOW();
                    RETURN NEW;
                END;
                $func$ LANGUAGE plpgsql;
            END IF;
        END $$;
    """))

    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_orders_updated_at ON orders;"))
    op.execute(sa.text("""
        CREATE TRIGGER trg_orders_updated_at
        BEFORE UPDATE ON orders
        FOR EACH ROW
        EXECUTE FUNCTION update_updated_at_column();
    """))

    # 3. Create order_items table
    op.create_table(
        'order_items',
        sa.Column('order_item_id', sa.BigInteger(), sa.Identity(always=False, start=1), nullable=False),
        sa.Column('order_id', sa.BigInteger(), nullable=False),
        sa.Column('product_id', sa.BigInteger(), nullable=False),
        sa.Column('product_title', sa.String(length=255), nullable=False),
        sa.Column('product_image_url', sa.String(length=500), nullable=True),
        sa.Column('quantity', sa.Integer(), server_default='1', nullable=False),
        sa.Column('price_at_purchase', sa.Numeric(precision=12, scale=0), nullable=False),
        sa.PrimaryKeyConstraint('order_item_id', name='pk_order_items'),
        sa.ForeignKeyConstraint(['order_id'], ['orders.order_id'], name='fk_order_items_orders', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['product_id'], ['products.product_id'], name='fk_order_items_products', ondelete='RESTRICT'),
        sa.UniqueConstraint('order_id', 'product_id', name='ux_order_items_order_product'),
        sa.CheckConstraint('quantity > 0', name='chk_order_items_quantity'),
        sa.CheckConstraint('price_at_purchase >= 0', name='chk_order_items_price'),
    )

    op.create_index('ix_order_items_product_id', 'order_items', ['product_id'])

    # 4. Create order_status_history table
    op.create_table(
        'order_status_history',
        sa.Column('history_id', sa.BigInteger(), sa.Identity(always=False, start=1), nullable=False),
        sa.Column('order_id', sa.BigInteger(), nullable=False),
        sa.Column('from_status', sa.String(length=12), nullable=True),
        sa.Column('to_status', sa.String(length=12), nullable=False),
        sa.Column('changed_by', sa.BigInteger(), nullable=True),
        sa.Column('note', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.PrimaryKeyConstraint('history_id', name='pk_order_status_history'),
        sa.ForeignKeyConstraint(['order_id'], ['orders.order_id'], name='fk_order_status_history_orders', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['changed_by'], ['users.user_id'], name='fk_order_status_history_users', ondelete='SET NULL'),
    )

    op.create_index('ix_order_status_history_order_id_created', 'order_status_history', ['order_id', 'created_at'])


def downgrade() -> None:
    op.drop_index('ix_order_status_history_order_id_created', table_name='order_status_history')
    op.drop_table('order_status_history')

    op.drop_index('ix_order_items_product_id', table_name='order_items')
    op.drop_table('order_items')

    op.execute(sa.text('DROP TRIGGER IF EXISTS trg_orders_updated_at ON orders;'))
    op.drop_index('ix_orders_paystatus_receipt_uploaded', table_name='orders')
    op.drop_index('ix_orders_status_paystatus_autocancel', table_name='orders')
    op.drop_index('ix_orders_seller_status_created', table_name='orders')
    op.drop_index('ix_orders_buyer_status_created', table_name='orders')
    op.drop_table('orders')

    op.execute(sa.text('DROP TYPE IF EXISTS payment_status_t;'))
