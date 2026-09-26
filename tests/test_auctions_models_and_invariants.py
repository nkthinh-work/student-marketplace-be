from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4
import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auctions.models import Auction, AuctionBid, AuctionStatus
from app.modules.categories.models import Category
from app.modules.orders.models import (
    FulfillmentMethod,
    Order,
    OrderItem,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
)
from app.modules.products.models import ListingType, Product, ProductStatus
from app.modules.users.models import User, UserRole, UserStatus


@pytest_asyncio.fixture
async def sample_category(db_session: AsyncSession) -> Category:
    cat = Category(name="Đồ Điện Tử", slug=f"do-dien-tu-{uuid4().hex[:6]}", is_deleted=False)
    db_session.add(cat)
    await db_session.flush()
    return cat


@pytest_asyncio.fixture
async def seller(db_session: AsyncSession) -> User:
    user = User(
        email=f"seller_{uuid4().hex[:6]}@ptit.edu.vn",
        full_name="Nguyễn Văn Bán",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def bidder(db_session: AsyncSession) -> User:
    user = User(
        email=f"bidder_{uuid4().hex[:6]}@ptit.edu.vn",
        full_name="Trần Thị Mua",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def product(db_session: AsyncSession, seller: User, sample_category: Category) -> Product:
    prod = Product(
        seller_id=seller.user_id,
        category_id=sample_category.category_id,
        title="Laptop Dell XPS 13",
        description="Đẹp như mới",
        listing_type=ListingType.AUCTION.value,
        price=Decimal("15000000"),
        stock=1,
        reserved_stock=0,
        status=ProductStatus.AVAILABLE.value,
        approval_status="APPROVED",
        view_count=0,
        is_deleted=False,
    )
    db_session.add(prod)
    await db_session.flush()
    return prod


@pytest.mark.asyncio
async def test_auction_db_check_bid_step_must_be_positive(db_session: AsyncSession, product: Product):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    auction = Auction(
        product_id=product.product_id,
        starting_price=Decimal("100000"),
        bid_step=Decimal("0"),  # INVALID (must be > 0)
        starts_at=now,
        ends_at=now + timedelta(hours=2),
        status=AuctionStatus.SCHEDULED.value,
    )
    db_session.add(auction)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_auction_db_check_time_window(db_session: AsyncSession, product: Product):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    auction = Auction(
        product_id=product.product_id,
        starting_price=Decimal("100000"),
        bid_step=Decimal("10000"),
        starts_at=now,
        ends_at=now - timedelta(hours=1),  # INVALID (ends_at <= starts_at)
        status=AuctionStatus.SCHEDULED.value,
    )
    db_session.add(auction)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_auction_db_check_scheduled_no_winner(db_session: AsyncSession, product: Product, bidder: User):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    auction = Auction(
        product_id=product.product_id,
        starting_price=Decimal("100000"),
        bid_step=Decimal("10000"),
        starts_at=now,
        ends_at=now + timedelta(hours=2),
        status=AuctionStatus.SCHEDULED.value,
        winner_id=bidder.user_id,  # INVALID on SCHEDULED
        final_price=Decimal("150000"),
        winner_checkout_deadline=now + timedelta(hours=26),
    )
    db_session.add(auction)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_auction_db_check_active_no_winner(db_session: AsyncSession, product: Product, bidder: User):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    auction = Auction(
        product_id=product.product_id,
        starting_price=Decimal("100000"),
        bid_step=Decimal("10000"),
        starts_at=now,
        ends_at=now + timedelta(hours=2),
        status=AuctionStatus.ACTIVE.value,
        winner_id=bidder.user_id,  # INVALID on ACTIVE
    )
    db_session.add(auction)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_auction_db_check_ended_with_winner_requires_all_fields(db_session: AsyncSession, product: Product, bidder: User):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    auction = Auction(
        product_id=product.product_id,
        starting_price=Decimal("100000"),
        bid_step=Decimal("10000"),
        starts_at=now,
        ends_at=now + timedelta(hours=2),
        status=AuctionStatus.ENDED.value,
        winner_id=bidder.user_id,
        final_price=Decimal("150000"),
        winner_checkout_deadline=None,  # INVALID: missing deadline
    )
    db_session.add(auction)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_auction_db_check_final_price_gte_starting_price(db_session: AsyncSession, product: Product, bidder: User):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    auction = Auction(
        product_id=product.product_id,
        starting_price=Decimal("100000"),
        bid_step=Decimal("10000"),
        starts_at=now,
        ends_at=now + timedelta(hours=2),
        status=AuctionStatus.ENDED.value,
        winner_id=bidder.user_id,
        final_price=Decimal("50000"),  # INVALID: final_price < starting_price
        winner_checkout_deadline=now + timedelta(hours=24),
    )
    db_session.add(auction)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_auction_db_check_ended_no_bids_valid(db_session: AsyncSession, product: Product):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    auction = Auction(
        product_id=product.product_id,
        starting_price=Decimal("100000"),
        bid_step=Decimal("10000"),
        starts_at=now,
        ends_at=now + timedelta(hours=2),
        status=AuctionStatus.ENDED.value,
        winner_id=None,
        final_price=None,
        winner_checkout_deadline=None,
    )
    db_session.add(auction)
    await db_session.flush()
    assert auction.auction_id is not None


@pytest.mark.asyncio
async def test_auction_bid_amount_must_be_positive(db_session: AsyncSession, product: Product, bidder: User):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    auction = Auction(
        product_id=product.product_id,
        starting_price=Decimal("0"),
        bid_step=Decimal("10000"),
        starts_at=now,
        ends_at=now + timedelta(hours=2),
        status=AuctionStatus.ACTIVE.value,
    )
    db_session.add(auction)
    await db_session.flush()

    bid = AuctionBid(
        auction_id=auction.auction_id,
        bidder_id=bidder.user_id,
        amount=Decimal("0"),  # INVALID (must be > 0)
    )
    db_session.add(bid)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_ux_auctions_product_active_partial_unique(db_session: AsyncSession, product: Product):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    auction1 = Auction(
        product_id=product.product_id,
        starting_price=Decimal("100000"),
        bid_step=Decimal("10000"),
        starts_at=now,
        ends_at=now + timedelta(hours=2),
        status=AuctionStatus.ACTIVE.value,
    )
    db_session.add(auction1)
    await db_session.flush()

    # Second active auction for same product must fail
    auction2 = Auction(
        product_id=product.product_id,
        starting_price=Decimal("100000"),
        bid_step=Decimal("10000"),
        starts_at=now,
        ends_at=now + timedelta(hours=2),
        status=AuctionStatus.SCHEDULED.value,
    )
    db_session.add(auction2)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_ux_auctions_allows_multiple_historical_ended_rounds(db_session: AsyncSession, product: Product):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    # Round 1: ENDED
    auction1 = Auction(
        product_id=product.product_id,
        starting_price=Decimal("100000"),
        bid_step=Decimal("10000"),
        starts_at=now - timedelta(days=2),
        ends_at=now - timedelta(days=1),
        status=AuctionStatus.ENDED.value,
    )
    db_session.add(auction1)
    await db_session.flush()

    # Round 2: ENDED
    auction2 = Auction(
        product_id=product.product_id,
        starting_price=Decimal("120000"),
        bid_step=Decimal("10000"),
        starts_at=now - timedelta(hours=10),
        ends_at=now - timedelta(hours=5),
        status=AuctionStatus.ENDED.value,
    )
    db_session.add(auction2)
    await db_session.flush()

    # Round 3: ACTIVE
    auction3 = Auction(
        product_id=product.product_id,
        starting_price=Decimal("150000"),
        bid_step=Decimal("10000"),
        starts_at=now,
        ends_at=now + timedelta(hours=5),
        status=AuctionStatus.ACTIVE.value,
    )
    db_session.add(auction3)
    await db_session.flush()

    assert auction1.auction_id != auction2.auction_id != auction3.auction_id


@pytest.mark.asyncio
async def test_ux_orders_auction_id_strictly_one_order_per_auction(
    db_session: AsyncSession, product: Product, seller: User, bidder: User
):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    auction = Auction(
        product_id=product.product_id,
        starting_price=Decimal("100000"),
        bid_step=Decimal("10000"),
        starts_at=now - timedelta(hours=3),
        ends_at=now - timedelta(hours=1),
        status=AuctionStatus.ENDED.value,
        winner_id=bidder.user_id,
        final_price=Decimal("200000"),
        winner_checkout_deadline=now + timedelta(hours=23),
    )
    db_session.add(auction)
    await db_session.flush()

    # Order 1
    order1 = Order(
        order_code="ORD-AUC-1",
        buyer_id=bidder.user_id,
        seller_id=seller.user_id,
        auction_id=auction.auction_id,
        status=OrderStatus.PENDING.value,
        payment_method=PaymentMethod.CASH_ON_MEETUP.value,
        payment_status=PaymentStatus.UNPAID,
        fulfillment_method=FulfillmentMethod.MEETUP.value,
        contact_name="Trần Thị Mua",
        contact_phone="0912345678",
        total_amount=Decimal("200000"),
    )
    db_session.add(order1)
    await db_session.flush()

    # Order 2 with same auction_id must fail unique constraint
    order2 = Order(
        order_code="ORD-AUC-2",
        buyer_id=bidder.user_id,
        seller_id=seller.user_id,
        auction_id=auction.auction_id,
        status=OrderStatus.PENDING.value,
        payment_method=PaymentMethod.CASH_ON_MEETUP.value,
        payment_status=PaymentStatus.UNPAID,
        fulfillment_method=FulfillmentMethod.MEETUP.value,
        contact_name="Trần Thị Mua",
        contact_phone="0912345678",
        total_amount=Decimal("200000"),
    )
    db_session.add(order2)
    with pytest.raises(IntegrityError):
        await db_session.flush()
