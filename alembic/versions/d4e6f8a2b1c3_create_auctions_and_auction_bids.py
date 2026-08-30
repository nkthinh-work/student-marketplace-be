"""create_auctions_and_auction_bids

Revision ID: d4e6f8a2b1c3
Revises: c3e5f8a1b2d4
Create Date: 2026-08-30 17:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e6f8a2b1c3'
down_revision: Union[str, None] = 'c3e5f8a1b2d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create auctions table
    op.create_table(
        'auctions',
        sa.Column('auction_id', sa.BigInteger(), sa.Identity(always=False, start=1), nullable=False),
        sa.Column('product_id', sa.BigInteger(), nullable=False),
        sa.Column('starting_price', sa.Numeric(precision=12, scale=0), nullable=False),
        sa.Column('bid_step', sa.Numeric(precision=12, scale=0), nullable=False),
        sa.Column('starts_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('ends_at', sa.DateTime(), nullable=False),
        sa.Column('status', sa.String(length=10), server_default='SCHEDULED', nullable=False),
        sa.Column('winner_id', sa.BigInteger(), nullable=True),
        sa.Column('final_price', sa.Numeric(precision=12, scale=0), nullable=True),
        sa.Column('winner_checkout_deadline', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.PrimaryKeyConstraint('auction_id', name='pk_auctions'),
        sa.ForeignKeyConstraint(['product_id'], ['products.product_id'], name='fk_auctions_product_id', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['winner_id'], ['users.user_id'], name='fk_auctions_winner_id', ondelete='RESTRICT'),
        sa.CheckConstraint('bid_step > 0', name='chk_auctions_bid_step'),
        sa.CheckConstraint('starting_price >= 0', name='chk_auctions_starting_price'),
        sa.CheckConstraint('ends_at > starts_at', name='chk_auctions_time_window'),
        sa.CheckConstraint("status IN ('SCHEDULED', 'ACTIVE', 'ENDED', 'CANCELLED')", name='chk_auctions_status'),
        sa.CheckConstraint('final_price IS NULL OR final_price >= starting_price', name='chk_auctions_final_price_gte_start'),
        sa.CheckConstraint(
            "status = 'ENDED' OR (winner_id IS NULL AND final_price IS NULL AND winner_checkout_deadline IS NULL)",
            name='chk_auctions_non_ended_no_winner'
        ),
        sa.CheckConstraint(
            "(winner_id IS NULL AND final_price IS NULL AND winner_checkout_deadline IS NULL) OR "
            "(winner_id IS NOT NULL AND final_price IS NOT NULL AND final_price > 0 AND winner_checkout_deadline IS NOT NULL)",
            name='chk_auctions_winner_consistency'
        ),
    )

    op.create_index(
        'ux_auctions_product_active',
        'auctions',
        ['product_id'],
        unique=True,
        postgresql_where=sa.text("status IN ('SCHEDULED', 'ACTIVE')")
    )
    op.create_index('ix_auctions_product_id', 'auctions', ['product_id'])
    op.create_index('ix_auctions_status_ends_at', 'auctions', ['status', 'ends_at'])
    op.create_index('ix_auctions_status_starts_at', 'auctions', ['status', 'starts_at'])
    op.create_index(
        'ix_auctions_winner_deadline',
        'auctions',
        ['status', 'winner_checkout_deadline'],
        postgresql_where=sa.text("winner_id IS NOT NULL")
    )

    # 2. updated_at trigger on auctions
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_auctions_updated_at ON auctions;"))
    op.execute(sa.text("""
        CREATE TRIGGER trg_auctions_updated_at
        BEFORE UPDATE ON auctions
        FOR EACH ROW
        EXECUTE FUNCTION update_updated_at_column();
    """))

    # 3. Create auction_bids table
    op.create_table(
        'auction_bids',
        sa.Column('bid_id', sa.BigInteger(), sa.Identity(always=False, start=1), nullable=False),
        sa.Column('auction_id', sa.BigInteger(), nullable=False),
        sa.Column('bidder_id', sa.BigInteger(), nullable=False),
        sa.Column('amount', sa.Numeric(precision=12, scale=0), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.PrimaryKeyConstraint('bid_id', name='pk_auction_bids'),
        sa.ForeignKeyConstraint(['auction_id'], ['auctions.auction_id'], name='fk_auction_bids_auction_id', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['bidder_id'], ['users.user_id'], name='fk_auction_bids_bidder_id', ondelete='RESTRICT'),
        sa.CheckConstraint('amount > 0', name='chk_auction_bids_amount'),
    )

    op.create_index(
        'ix_auction_bids_auction_amount_created',
        'auction_bids',
        ['auction_id', sa.text('amount DESC'), sa.text('created_at ASC'), sa.text('bid_id ASC')]
    )
    op.create_index('ix_auction_bids_bidder_created', 'auction_bids', ['bidder_id', 'created_at'])

    # 4. Add auction_id column to orders table and single-order-per-auction index
    op.add_column('orders', sa.Column('auction_id', sa.BigInteger(), nullable=True))
    op.create_foreign_key('fk_orders_auction_id', 'orders', 'auctions', ['auction_id'], ['auction_id'], ondelete='RESTRICT')
    op.create_index(
        'ux_orders_auction_id',
        'orders',
        ['auction_id'],
        unique=True,
        postgresql_where=sa.text('auction_id IS NOT NULL')
    )


def downgrade() -> None:
    # 1. Drop orders.auction_id index, FK, and column
    op.drop_index('ux_orders_auction_id', table_name='orders')
    op.drop_constraint('fk_orders_auction_id', 'orders', type_='foreignkey')
    op.drop_column('orders', 'auction_id')

    # 2. Drop auction_bids indexes and table
    op.drop_index('ix_auction_bids_bidder_created', table_name='auction_bids')
    op.drop_index('ix_auction_bids_auction_amount_created', table_name='auction_bids')
    op.drop_table('auction_bids')

    # 3. Drop auctions trigger, indexes, and table
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_auctions_updated_at ON auctions;"))
    op.drop_index('ix_auctions_winner_deadline', table_name='auctions')
    op.drop_index('ix_auctions_status_starts_at', table_name='auctions')
    op.drop_index('ix_auctions_status_ends_at', table_name='auctions')
    op.drop_index('ix_auctions_product_id', table_name='auctions')
    op.drop_index('ux_auctions_product_active', table_name='auctions')
    op.drop_table('auctions')
