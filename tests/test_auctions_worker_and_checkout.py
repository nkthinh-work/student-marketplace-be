from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.modules.auctions.models import Auction, AuctionBid, AuctionStatus
from app.modules.auctions.schemas import PlaceBidRequest, WinnerCheckoutRequest
from app.modules.auctions.service import (
    AuctionService,
    run_auction_close_sweep,
    run_auction_scheduled_sweep,
    run_winner_timeout_sweep,
)
from app.modules.categories.models import Category
from app.modules.orders.models import (
    CancelledBy,
    FulfillmentMethod,
    Order,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
)
from app.modules.orders.schemas import CancelOrderRequest
from app.modules.orders.service import OrderService
from app.modules.products.models import ListingType, Product, ProductStatus
from app.modules.users.models import User, UserAuthIdentity, UserRole, UserStatus


@pytest_asyncio.fixture
async def sample_category(db_session: AsyncSession) -> Category:
    cat = Category(name="Đồ Gia Dụng", slug=f"do-gia-dung-{uuid4().hex[:6]}", is_deleted=False)
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
async def winner(db_session: AsyncSession) -> User:
    user = User(
        email=f"winner_{uuid4().hex[:6]}@ptit.edu.vn",
        full_name="Hoàng Văn Thắng",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def other_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"other_{uuid4().hex[:6]}@ptit.edu.vn",
        full_name="Người Dùng Khác",
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
        title="Quạt đứng Senko",
        description="Quạt chạy êm",
        listing_type=ListingType.AUCTION.value,
        price=Decimal("150000"),
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
async def test_worker_catchup_scheduled_to_active(
    db_session: AsyncSession, product: Product
):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    auction = Auction(
        product_id=product.product_id,
        starting_price=Decimal("150000"),
        bid_step=Decimal("10000"),
        starts_at=now - timedelta(minutes=5),
        ends_at=now + timedelta(hours=2),
        status=AuctionStatus.SCHEDULED.value,
    )
    db_session.add(auction)
    await db_session.flush()

    session_maker = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    processed = await run_auction_scheduled_sweep(session_maker)
    assert processed >= 1

    await db_session.refresh(auction)
    assert auction.status == AuctionStatus.ACTIVE.value


@pytest.mark.asyncio
async def test_worker_catchup_expired_scheduled_directly_to_ended(
    db_session: AsyncSession, product: Product
):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    # Auction expired while the server was down/scheduled
    auction = Auction(
        product_id=product.product_id,
        starting_price=Decimal("150000"),
        bid_step=Decimal("10000"),
        starts_at=now - timedelta(hours=5),
        ends_at=now - timedelta(hours=1),
        status=AuctionStatus.SCHEDULED.value,
    )
    db_session.add(auction)
    await db_session.flush()

    session_maker = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    processed = await run_auction_scheduled_sweep(session_maker)
    assert processed >= 1

    await db_session.refresh(auction)
    assert auction.status == AuctionStatus.ENDED.value
    assert auction.winner_id is None
    assert auction.final_price is None
    assert auction.winner_checkout_deadline is None


@pytest.mark.asyncio
async def test_worker_close_active_auction_with_winner(
    db_session: AsyncSession, product: Product, winner: User
):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    auction = Auction(
        product_id=product.product_id,
        starting_price=Decimal("150000"),
        bid_step=Decimal("10000"),
        starts_at=now - timedelta(hours=2),
        ends_at=now - timedelta(minutes=1),
        status=AuctionStatus.ACTIVE.value,
    )
    db_session.add(auction)
    await db_session.flush()

    bid = AuctionBid(
        auction_id=auction.auction_id,
        bidder_id=winner.user_id,
        amount=Decimal("200000"),
        created_at=now - timedelta(minutes=30),
    )
    db_session.add(bid)
    await db_session.flush()

    session_maker = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    closed = await run_auction_close_sweep(session_maker)
    assert closed >= 1

    await db_session.refresh(auction)
    assert auction.status == AuctionStatus.ENDED.value
    assert auction.winner_id == winner.user_id
    assert auction.final_price == Decimal("200000")
    assert auction.winner_checkout_deadline is not None

    # Stock reserved for winner
    await db_session.refresh(product)
    assert product.reserved_stock == 1


@pytest.mark.asyncio
async def test_worker_release_unpurchased_winner_reservation(
    db_session: AsyncSession, product: Product, winner: User
):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    # Winner reservation expired
    auction = Auction(
        product_id=product.product_id,
        starting_price=Decimal("150000"),
        bid_step=Decimal("10000"),
        starts_at=now - timedelta(days=2),
        ends_at=now - timedelta(days=1),
        status=AuctionStatus.ENDED.value,
        winner_id=winner.user_id,
        final_price=Decimal("200000"),
        winner_checkout_deadline=now - timedelta(minutes=5),
    )
    db_session.add(auction)
    product.reserved_stock = 1
    await db_session.flush()

    session_maker = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    released = await run_winner_timeout_sweep(session_maker)
    assert released >= 1

    await db_session.refresh(product)
    assert product.reserved_stock == 0


@pytest.mark.asyncio
async def test_winner_checkout_and_single_order_lifecycle(
    db_session: AsyncSession, product: Product, winner: User, other_user: User
):
    service = AuctionService(db_session)
    order_service = OrderService(db_session)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    auction = Auction(
        product_id=product.product_id,
        starting_price=Decimal("150000"),
        bid_step=Decimal("10000"),
        starts_at=now - timedelta(hours=2),
        ends_at=now - timedelta(hours=1),
        status=AuctionStatus.ENDED.value,
        winner_id=winner.user_id,
        final_price=Decimal("250000"),
        winner_checkout_deadline=now + timedelta(hours=23),
    )
    db_session.add(auction)
    product.reserved_stock = 1
    await db_session.flush()

    # 1. Non-winner cannot checkout
    with pytest.raises(Exception) as exc:
        await service.winner_checkout(
            other_user,
            auction.auction_id,
            WinnerCheckoutRequest(
                payment_method=PaymentMethod.CASH_ON_MEETUP,
                fulfillment_method=FulfillmentMethod.MEETUP,
                meetup_place="Cổng trường PTIT",
                contact_name="Người Dùng Khác",
                contact_phone="0911111111",
            ),
        )
    assert "Bạn không phải người thắng phiên đấu giá này." in str(exc.value)

    # 2. Winner checks out successfully
    order = await service.winner_checkout(
        winner,
        auction.auction_id,
        WinnerCheckoutRequest(
            payment_method=PaymentMethod.CASH_ON_MEETUP,
            fulfillment_method=FulfillmentMethod.MEETUP,
            meetup_place="Cổng trường PTIT",
            contact_name="Hoàng Văn Thắng",
            contact_phone="0988888888",
        ),
    )
    assert order.buyer_id == winner.user_id
    assert order.auction_id == auction.auction_id
    assert order.total_amount == Decimal("250000")
    assert order.status == OrderStatus.PENDING.value

    # Stock reservation was transferred: reserved_stock remains 1 (no double reservation!)
    await db_session.refresh(product)
    assert product.reserved_stock == 1

    # 3. Second checkout attempt on same auction is strictly rejected
    with pytest.raises(Exception) as exc:
        await service.winner_checkout(
            winner,
            auction.auction_id,
            WinnerCheckoutRequest(
                payment_method=PaymentMethod.CASH_ON_MEETUP,
                fulfillment_method=FulfillmentMethod.MEETUP,
                meetup_place="Cổng trường PTIT",
                contact_name="Hoàng Văn Thắng",
                contact_phone="0988888888",
            ),
        )
    assert "Quyền mua từ phiên đấu giá này đã được sử dụng" in str(exc.value)

    # 4. Winner cancels order -> reservation is released, but auction right remains consumed
    await order_service.cancel_order(
        order_id=order.order_id,
        current_user=winner,
        payload=CancelOrderRequest(cancel_reason="Đổi ý không mua nữa"),
    )
    await db_session.refresh(product)
    assert product.reserved_stock == 0

    # Checking out same auction again is still rejected
    with pytest.raises(Exception) as exc:
        await service.winner_checkout(
            winner,
            auction.auction_id,
            WinnerCheckoutRequest(
                payment_method=PaymentMethod.CASH_ON_MEETUP,
                fulfillment_method=FulfillmentMethod.MEETUP,
                meetup_place="Cổng trường PTIT",
                contact_name="Hoàng Văn Thắng",
                contact_phone="0988888888",
            ),
        )
    assert "Quyền mua từ phiên đấu giá này đã được sử dụng" in str(exc.value)


@pytest.mark.asyncio
async def test_on_demand_finalization_on_get_auction_detail_and_by_product(
    db_session: AsyncSession, seller: User, winner: User, sample_category: Category
):
    service = AuctionService(db_session)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    prod = Product(
        seller_id=seller.user_id,
        category_id=sample_category.category_id,
        title="Máy ảnh Canon",
        price=Decimal("500000"),
        stock=1,
        reserved_stock=0,
        listing_type=ListingType.AUCTION.value,
        status=ProductStatus.AVAILABLE.value,
        approval_status="APPROVED",
    )
    db_session.add(prod)
    await db_session.flush()

    # Auction whose ends_at is 1 second in the past
    auction = Auction(
        product_id=prod.product_id,
        starting_price=Decimal("500000"),
        bid_step=Decimal("10000"),
        starts_at=now - timedelta(hours=1),
        ends_at=now - timedelta(seconds=1),
        status=AuctionStatus.ACTIVE.value,
    )
    db_session.add(auction)
    await db_session.flush()

    # Place a bid of 540,000
    bid = AuctionBid(
        auction_id=auction.auction_id,
        bidder_id=winner.user_id,
        amount=Decimal("540000"),
    )
    db_session.add(bid)
    await db_session.flush()

    # 1. Calling get_auction_by_product automatically closes the auction on-the-fly
    detail = await service.get_auction_by_product(prod.product_id, current_user=winner)
    assert detail.status == "ENDED"
    assert detail.final_price == Decimal("540000")
    assert detail.has_winner is True
    assert detail.is_current_user_winner is True
    assert detail.winner_checkout_state == "WAITING"

    # Verify DB state
    await db_session.refresh(auction)
    assert auction.status == AuctionStatus.ENDED.value
    assert auction.winner_id == winner.user_id
    assert auction.final_price == Decimal("540000")
    assert auction.winner_checkout_deadline is not None

    await db_session.refresh(prod)
    assert prod.reserved_stock == 1

    # 2. Calling get_auction_detail as seller shows winner waiting state
    seller_detail = await service.get_auction_detail(auction.auction_id, current_user=seller)
    assert seller_detail.status == "ENDED"
    assert seller_detail.winner_checkout_state == "WAITING"
    assert seller_detail.is_current_user_winner is False


@pytest.mark.asyncio
async def test_close_sweep_resilience_to_pubsub_errors(
    db_session: AsyncSession, seller: User, winner: User, sample_category: Category
):
    service = AuctionService(db_session)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    prod = Product(
        seller_id=seller.user_id,
        category_id=sample_category.category_id,
        title="iPad Air",
        price=Decimal("8000000"),
        stock=1,
        reserved_stock=0,
        listing_type=ListingType.AUCTION.value,
        status=ProductStatus.AVAILABLE.value,
        approval_status="APPROVED",
    )
    db_session.add(prod)
    await db_session.flush()

    auction = Auction(
        product_id=prod.product_id,
        starting_price=Decimal("8000000"),
        bid_step=Decimal("50000"),
        starts_at=now - timedelta(hours=1),
        ends_at=now - timedelta(seconds=5),
        status=AuctionStatus.ACTIVE.value,
    )
    db_session.add(auction)
    await db_session.flush()

    # Even if publish_auction_event throws an error, the DB transaction succeeds and state is ENDED
    with patch("app.modules.auctions.service.publish_auction_event", side_effect=Exception("Redis connection refused")):
        auc = await service.close_single_auction_if_expired(auction.auction_id, now)
        assert auc.status == AuctionStatus.ENDED.value
        assert prod.reserved_stock == 0  # no bids, so 0 reserved stock


@pytest.mark.asyncio
async def test_expired_active_auction_direct_checkout_without_prior_get(
    db_session: AsyncSession, seller: User, winner: User, sample_category: Category
):
    service = AuctionService(db_session)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    prod = Product(
        seller_id=seller.user_id,
        category_id=sample_category.category_id,
        title="Laptop Dell Gaming",
        price=Decimal("15000000"),
        stock=1,
        reserved_stock=0,
        listing_type=ListingType.AUCTION.value,
        status=ProductStatus.AVAILABLE.value,
        approval_status="APPROVED",
    )
    db_session.add(prod)
    await db_session.flush()

    # Auction still marked ACTIVE in DB, but ends_at is in past
    auction = Auction(
        product_id=prod.product_id,
        starting_price=Decimal("15000000"),
        bid_step=Decimal("100000"),
        starts_at=now - timedelta(hours=2),
        ends_at=now - timedelta(seconds=10),
        status=AuctionStatus.ACTIVE.value,
    )
    db_session.add(auction)
    await db_session.flush()

    bid = AuctionBid(
        auction_id=auction.auction_id,
        bidder_id=winner.user_id,
        amount=Decimal("15500000"),
    )
    db_session.add(bid)
    await db_session.flush()

    # Direct POST checkout without prior GET detail call
    order = await service.winner_checkout(
        winner,
        auction.auction_id,
        WinnerCheckoutRequest(
            payment_method=PaymentMethod.CASH_ON_MEETUP,
            fulfillment_method=FulfillmentMethod.MEETUP,
            meetup_place="Học viện Công nghệ Bưu chính Viễn thông",
            contact_name="Hoàng Văn Thắng",
            contact_phone="0988888888",
        ),
    )
    assert order.buyer_id == winner.user_id
    assert order.auction_id == auction.auction_id
    assert order.total_amount == Decimal("15500000")

    # DB Auction is now ENDED and has winner
    await db_session.refresh(auction)
    assert auction.status == AuctionStatus.ENDED.value
    assert auction.winner_id == winner.user_id
    assert auction.final_price == Decimal("15500000")

    # Stock reservation is exactly 1
    await db_session.refresh(prod)
    assert prod.stock == 1
    assert prod.reserved_stock == 1


@pytest.mark.asyncio
async def test_active_unexpired_auction_checkout_rejected(
    db_session: AsyncSession, seller: User, winner: User, sample_category: Category
):
    service = AuctionService(db_session)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    prod = Product(
        seller_id=seller.user_id,
        category_id=sample_category.category_id,
        title="Bàn phím cơ AKKO",
        price=Decimal("1000000"),
        stock=1,
        reserved_stock=0,
        listing_type=ListingType.AUCTION.value,
        status=ProductStatus.AVAILABLE.value,
        approval_status="APPROVED",
    )
    db_session.add(prod)
    await db_session.flush()

    # Auction is ACTIVE and ends_at is in FUTURE
    auction = Auction(
        product_id=prod.product_id,
        starting_price=Decimal("1000000"),
        bid_step=Decimal("50000"),
        starts_at=now - timedelta(minutes=10),
        ends_at=now + timedelta(hours=1),
        status=AuctionStatus.ACTIVE.value,
    )
    db_session.add(auction)
    await db_session.flush()

    with pytest.raises(Exception) as exc:
        await service.winner_checkout(
            winner,
            auction.auction_id,
            WinnerCheckoutRequest(
                payment_method=PaymentMethod.CASH_ON_MEETUP,
                fulfillment_method=FulfillmentMethod.MEETUP,
                meetup_place="Học viện Bưu chính Viễn thông",
                contact_name="Hoàng Văn Thắng",
                contact_phone="0988888888",
            ),
        )
    assert "Phiên đấu giá chưa kết thúc." in str(exc.value)


@pytest.mark.asyncio
async def test_get_my_won_auctions_service_scenarios(
    db_session: AsyncSession, seller: User, winner: User, other_user: User, sample_category: Category
):
    service = AuctionService(db_session)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # 1. Product and Auction that expired while active with a bid from winner
    prod1 = Product(
        seller_id=seller.user_id,
        category_id=sample_category.category_id,
        title="Laptop Thinkpad T480",
        price=Decimal("8000000"),
        stock=1,
        reserved_stock=0,
        listing_type=ListingType.AUCTION.value,
        status=ProductStatus.AVAILABLE.value,
        approval_status="APPROVED",
    )
    db_session.add(prod1)
    await db_session.flush()

    auc1 = Auction(
        product_id=prod1.product_id,
        starting_price=Decimal("8000000"),
        bid_step=Decimal("100000"),
        starts_at=now - timedelta(hours=2),
        ends_at=now - timedelta(minutes=5),
        status=AuctionStatus.ACTIVE.value,
    )
    db_session.add(auc1)
    await db_session.flush()

    bid1 = AuctionBid(
        auction_id=auc1.auction_id,
        bidder_id=winner.user_id,
        amount=Decimal("8500000"),
    )
    db_session.add(bid1)
    await db_session.flush()

    # 2. Product and Auction already ended and expired deadline
    prod2 = Product(
        seller_id=seller.user_id,
        category_id=sample_category.category_id,
        title="Tai nghe Sony WH-1000XM4",
        price=Decimal("4000000"),
        stock=1,
        reserved_stock=0,
        listing_type=ListingType.AUCTION.value,
        status=ProductStatus.AVAILABLE.value,
        approval_status="APPROVED",
    )
    db_session.add(prod2)
    await db_session.flush()

    auc2 = Auction(
        product_id=prod2.product_id,
        starting_price=Decimal("4000000"),
        bid_step=Decimal("50000"),
        starts_at=now - timedelta(days=3),
        ends_at=now - timedelta(days=2),
        status=AuctionStatus.ENDED.value,
        winner_id=winner.user_id,
        final_price=Decimal("4200000"),
        winner_checkout_deadline=now - timedelta(hours=1),  # EXPIRED
    )
    db_session.add(auc2)
    await db_session.flush()

    # Query winner's won auctions
    won_items = await service.get_my_won_auctions(winner)
    assert len(won_items) == 1
    assert won_items[0].auction_id == auc1.auction_id
    assert won_items[0].product_id == prod1.product_id
    assert won_items[0].final_price == Decimal("8500000")

    # Other user sees 0
    other_items = await service.get_my_won_auctions(other_user)
    assert len(other_items) == 0

    # Seller sees 0
    seller_items = await service.get_my_won_auctions(seller)
    assert len(seller_items) == 0


@pytest.mark.asyncio
async def test_seller_cannot_delete_or_hide_product_with_active_winner_right(
    db_session: AsyncSession, seller: User, winner: User, sample_category: Category
):
    from app.modules.products.service import ProductService
    from app.modules.products.schemas import ProductUpdate

    prod_service = ProductService(db_session)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # Create product and ended auction with winner
    prod = Product(
        seller_id=seller.user_id,
        category_id=sample_category.category_id,
        title="Laptop Dell XPS 13",
        price=Decimal("15000000"),
        stock=1,
        reserved_stock=1,
        listing_type=ListingType.AUCTION.value,
        status=ProductStatus.AVAILABLE.value,
        approval_status="APPROVED",
    )
    db_session.add(prod)
    await db_session.flush()

    auc = Auction(
        product_id=prod.product_id,
        starting_price=Decimal("15000000"),
        bid_step=Decimal("100000"),
        starts_at=now - timedelta(hours=2),
        ends_at=now - timedelta(minutes=10),
        status=AuctionStatus.ENDED.value,
        winner_id=winner.user_id,
        final_price=Decimal("16000000"),
        winner_checkout_deadline=now + timedelta(hours=23),
    )
    db_session.add(auc)
    await db_session.flush()

    # 1. Seller attempts to delete product -> BLOCKED with controlled business message
    with pytest.raises(Exception) as exc_del:
        await prod_service.soft_delete_product(prod.product_id, seller)
    assert "Không thể xóa tin khi người thắng đấu giá vẫn còn thời hạn đặt mua." in str(exc_del.value)

    # 2. Seller attempts to hide product -> BLOCKED
    with pytest.raises(Exception) as exc_hide:
        await prod_service.update_product(
            prod.product_id,
            seller,
            ProductUpdate(status=ProductStatus.HIDDEN),
        )
    assert "Không thể ẩn sản phẩm khi người thắng đấu giá vẫn còn thời hạn đặt mua." in str(exc_hide.value)

    # 3. If deadline expires, soft delete succeeds
    auc.winner_checkout_deadline = now - timedelta(minutes=1)
    await db_session.flush()

    await prod_service.soft_delete_product(prod.product_id, seller)
    await db_session.refresh(prod)
    assert prod.is_deleted is True


@pytest.mark.asyncio
async def test_legacy_orphan_won_auction_excluded_from_my_won(
    db_session: AsyncSession, seller: User, winner: User, sample_category: Category
):
    service = AuctionService(db_session)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # Soft-deleted product with active winner auction
    prod = Product(
        seller_id=seller.user_id,
        category_id=sample_category.category_id,
        title="Orphan Product",
        price=Decimal("1000000"),
        stock=1,
        reserved_stock=1,
        listing_type=ListingType.AUCTION.value,
        status=ProductStatus.AVAILABLE.value,
        approval_status="APPROVED",
        is_deleted=True,
    )
    db_session.add(prod)
    await db_session.flush()

    auc = Auction(
        product_id=prod.product_id,
        starting_price=Decimal("1000000"),
        bid_step=Decimal("50000"),
        starts_at=now - timedelta(hours=2),
        ends_at=now - timedelta(minutes=10),
        status=AuctionStatus.ENDED.value,
        winner_id=winner.user_id,
        final_price=Decimal("1200000"),
        winner_checkout_deadline=now + timedelta(hours=23),
    )
    db_session.add(auc)
    await db_session.flush()

    won_items = await service.get_my_won_auctions(winner)
    # The orphan soft-deleted product is excluded
    assert len([item for item in won_items if item.auction_id == auc.auction_id]) == 0
