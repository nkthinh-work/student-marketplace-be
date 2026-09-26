from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auctions.models import Auction, AuctionBid, AuctionStatus
from app.modules.auctions.schemas import AuctionCreateRequest, PlaceBidRequest
from app.modules.auctions.service import AuctionService
from app.modules.categories.models import Category
from app.modules.notifications.models import Notification, NotificationType
from app.modules.products.models import ListingType, Product, ProductStatus
from app.modules.users.models import User, UserAuthIdentity, UserRole, UserStatus


@pytest_asyncio.fixture
async def sample_category(db_session: AsyncSession) -> Category:
    cat = Category(
        name="Đồ Điện Tử Test",
        slug=f"dien-tu-test-{uuid4().hex[:6]}",
        is_deleted=False,
    )
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
    identity = UserAuthIdentity(
        user_id=user.user_id,
        provider="FIREBASE",
        provider_uid=f"uid_{uuid4().hex[:8]}",
    )
    db_session.add(identity)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def buyer1(db_session: AsyncSession) -> User:
    user = User(
        email=f"buyer1_{uuid4().hex[:6]}@ptit.edu.vn",
        full_name="Trần Văn Mua",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    identity = UserAuthIdentity(
        user_id=user.user_id,
        provider="FIREBASE",
        provider_uid=f"uid_{uuid4().hex[:8]}",
    )
    db_session.add(identity)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def buyer2(db_session: AsyncSession) -> User:
    user = User(
        email=f"buyer2_{uuid4().hex[:6]}@ptit.edu.vn",
        full_name="Lê Thị Trúng",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    await db_session.flush()
    identity = UserAuthIdentity(
        user_id=user.user_id,
        provider="FIREBASE",
        provider_uid=f"uid_{uuid4().hex[:8]}",
    )
    db_session.add(identity)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def product(db_session: AsyncSession, seller: User, sample_category: Category) -> Product:
    prod = Product(
        seller_id=seller.user_id,
        category_id=sample_category.category_id,
        title="Bàn phím cơ DareU",
        description="Bàn phím cơ còn mới 99%",
        listing_type=ListingType.FIXED_PRICE.value,
        price=Decimal("200000"),
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


@pytest_asyncio.fixture
async def active_auction(db_session: AsyncSession, seller: User, product: Product) -> Auction:
    service = AuctionService(db_session)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    auc_res = await service.enable_auction(
        seller,
        AuctionCreateRequest(
            product_id=product.product_id,
            bid_step=Decimal("20000"),
            starts_at=None,
            ends_at=now + timedelta(hours=2),
        ),
    )
    # Fetch ORM Auction
    res = await db_session.execute(select(Auction).where(Auction.auction_id == auc_res.auction_id))
    return res.scalar_one()


@pytest.mark.asyncio
async def test_first_bid_creates_auction_bid_notification_for_seller_and_no_outbid(
    db_session: AsyncSession, seller: User, buyer1: User, active_auction: Auction
):
    service = AuctionService(db_session)

    with patch("app.modules.auctions.service.publish_user_event", new_callable=AsyncMock) as mock_pub_user, \
         patch("app.modules.auctions.service.publish_auction_event", new_callable=AsyncMock) as mock_pub_auction:

        bid = await service.place_bid(
            buyer1,
            active_auction.auction_id,
            PlaceBidRequest(amount=Decimal("200000")),
        )
        assert bid.amount == Decimal("200000")

        # Verify DB notifications
        res = await db_session.execute(
            select(Notification).where(Notification.ref_id == active_auction.auction_id)
        )
        notifications = res.scalars().all()

        # Exactly 1 notification created (for seller)
        assert len(notifications) == 1
        seller_notif = notifications[0]
        assert seller_notif.user_id == seller.user_id
        assert seller_notif.type == NotificationType.AUCTION_BID.value
        assert seller_notif.ref_type == "AUCTION"
        assert seller_notif.ref_id == active_auction.auction_id
        assert "200,000 đ" in seller_notif.body

        # Displaced bidder count is 0, buyer gets 0 notifications
        buyer_notifs = [n for n in notifications if n.user_id == buyer1.user_id]
        assert len(buyer_notifs) == 0

        # Verify realtime publication
        mock_pub_auction.assert_awaited_once()
        mock_pub_user.assert_awaited_once()
        call_args = mock_pub_user.call_args[0]
        assert call_args[0] == seller.user_id
        assert call_args[1]["type"] == "NOTIFICATION_CREATED"
        assert call_args[1]["notification"]["type"] == NotificationType.AUCTION_BID.value


@pytest.mark.asyncio
async def test_outbid_creates_notification_for_displaced_bidder_only(
    db_session: AsyncSession, seller: User, buyer1: User, buyer2: User, active_auction: Auction
):
    service = AuctionService(db_session)

    # 1. Buyer 1 places first bid: 200k
    await service.place_bid(
        buyer1,
        active_auction.auction_id,
        PlaceBidRequest(amount=Decimal("200000")),
    )

    # 2. Buyer 2 places higher bid: 250k (min is 220k)
    with patch("app.modules.auctions.service.publish_user_event", new_callable=AsyncMock) as mock_pub_user:
        await service.place_bid(
            buyer2,
            active_auction.auction_id,
            PlaceBidRequest(amount=Decimal("250000")),
        )

        # Verify DB notifications
        res = await db_session.execute(
            select(Notification)
            .where(Notification.ref_id == active_auction.auction_id)
            .order_by(Notification.notification_id.asc())
        )
        all_notifs = res.scalars().all()

        # Total notifications so far:
        # 1. Seller AUCTION_BID (from bid 1)
        # 2. Seller AUCTION_BID (from bid 2)
        # 3. Buyer 1 AUCTION_OUTBID (from bid 2 displacing Buyer 1)
        assert len(all_notifs) == 3

        seller_notifs = [n for n in all_notifs if n.user_id == seller.user_id]
        assert len(seller_notifs) == 2

        outbid_notifs = [n for n in all_notifs if n.type == NotificationType.AUCTION_OUTBID.value]
        assert len(outbid_notifs) == 1
        outbid = outbid_notifs[0]
        assert outbid.user_id == buyer1.user_id  # Buyer 1 displaced!
        assert outbid.ref_type == "AUCTION"
        assert outbid.ref_id == active_auction.auction_id
        assert "250,000 đ" in outbid.body

        # Buyer 2 (new highest bidder) must have ZERO outbid notifications
        buyer2_outbids = [n for n in all_notifs if n.user_id == buyer2.user_id]
        assert len(buyer2_outbids) == 0

        # Verify realtime: both seller and buyer1 received NOTIFICATION_CREATED
        user_ids_notified = [c[0][0] for c in mock_pub_user.call_args_list]
        assert seller.user_id in user_ids_notified
        assert buyer1.user_id in user_ids_notified
        assert buyer2.user_id not in user_ids_notified


@pytest.mark.asyncio
async def test_self_raise_does_not_create_outbid_notification(
    db_session: AsyncSession, seller: User, buyer1: User, active_auction: Auction
):
    service = AuctionService(db_session)

    # 1. Buyer 1 places first bid: 200k
    await service.place_bid(
        buyer1,
        active_auction.auction_id,
        PlaceBidRequest(amount=Decimal("200000")),
    )

    # 2. Buyer 1 raises their own bid to 240k
    with patch("app.modules.auctions.service.publish_user_event", new_callable=AsyncMock) as mock_pub_user:
        await service.place_bid(
            buyer1,
            active_auction.auction_id,
            PlaceBidRequest(amount=Decimal("240000")),
        )

        # Verify DB notifications
        res = await db_session.execute(
            select(Notification).where(Notification.ref_id == active_auction.auction_id)
        )
        all_notifs = res.scalars().all()

        # Must have:
        # - 2 seller AUCTION_BID notifications
        # - 0 AUCTION_OUTBID notifications (self-raise does not outbid oneself!)
        assert len(all_notifs) == 2
        for n in all_notifs:
            assert n.type == NotificationType.AUCTION_BID.value
            assert n.user_id == seller.user_id

        # Realtime: only seller notified, buyer1 not notified of outbid
        user_ids_notified = [c[0][0] for c in mock_pub_user.call_args_list]
        assert seller.user_id in user_ids_notified
        assert buyer1.user_id not in user_ids_notified


@pytest.mark.asyncio
async def test_invalid_bid_creates_zero_notifications(
    db_session: AsyncSession, seller: User, buyer1: User, active_auction: Auction
):
    service = AuctionService(db_session)

    # Bid below minimum next bid (200k)
    with pytest.raises(Exception):
        await service.place_bid(
            buyer1,
            active_auction.auction_id,
            PlaceBidRequest(amount=Decimal("150000")),
        )

    # Verify zero notifications in DB
    res = await db_session.execute(
        select(Notification).where(Notification.ref_id == active_auction.auction_id)
    )
    assert len(res.scalars().all()) == 0


@pytest.mark.asyncio
async def test_auction_end_with_winner_notifies_seller_and_winner(
    db_session: AsyncSession, seller: User, buyer1: User, active_auction: Auction
):
    service = AuctionService(db_session)

    # 1. Place a bid
    await service.place_bid(
        buyer1,
        active_auction.auction_id,
        PlaceBidRequest(amount=Decimal("220000")),
    )

    # 2. Fast forward time past ends_at
    future_time = active_auction.ends_at + timedelta(seconds=10)

    with patch("app.modules.auctions.service.publish_user_event", new_callable=AsyncMock) as mock_pub_user, \
         patch("app.modules.auctions.service.publish_auction_event", new_callable=AsyncMock) as mock_pub_auction:

        auc = await service.close_single_auction_if_expired(active_auction.auction_id, future_time)
        assert auc.status == AuctionStatus.ENDED.value

        # Verify DB notifications
        res = await db_session.execute(
            select(Notification).where(
                Notification.ref_id == active_auction.auction_id,
                Notification.type.in_([NotificationType.AUCTION_ENDED.value, NotificationType.AUCTION_WON.value]),
            )
        )
        end_notifs = res.scalars().all()
        assert len(end_notifs) == 2

        # Seller AUCTION_ENDED
        seller_end = next(n for n in end_notifs if n.type == NotificationType.AUCTION_ENDED.value)
        assert seller_end.user_id == seller.user_id
        assert "220,000 đ" in seller_end.body

        # Winner AUCTION_WON
        winner_notif = next(n for n in end_notifs if n.type == NotificationType.AUCTION_WON.value)
        assert winner_notif.user_id == buyer1.user_id
        assert "220,000 đ" in winner_notif.body

        # Realtime: auction event + both users notified
        mock_pub_auction.assert_awaited_once()
        user_ids_notified = [c[0][0] for c in mock_pub_user.call_args_list]
        assert seller.user_id in user_ids_notified
        assert buyer1.user_id in user_ids_notified


@pytest.mark.asyncio
async def test_auction_end_without_bids_notifies_seller_only(
    db_session: AsyncSession, seller: User, active_auction: Auction
):
    service = AuctionService(db_session)
    future_time = active_auction.ends_at + timedelta(seconds=10)

    with patch("app.modules.auctions.service.publish_user_event", new_callable=AsyncMock) as mock_pub_user:
        auc = await service.close_single_auction_if_expired(active_auction.auction_id, future_time)
        assert auc.status == AuctionStatus.ENDED.value

        res = await db_session.execute(
            select(Notification).where(
                Notification.ref_id == active_auction.auction_id,
                Notification.type.in_([NotificationType.AUCTION_ENDED.value, NotificationType.AUCTION_WON.value]),
            )
        )
        end_notifs = res.scalars().all()

        # Exactly 1 notification (seller AUCTION_ENDED), 0 AUCTION_WON
        assert len(end_notifs) == 1
        seller_end = end_notifs[0]
        assert seller_end.user_id == seller.user_id
        assert seller_end.type == NotificationType.AUCTION_ENDED.value
        assert "chưa có người thắng" in seller_end.body

        # Realtime
        user_ids_notified = [c[0][0] for c in mock_pub_user.call_args_list]
        assert user_ids_notified == [seller.user_id]


@pytest.mark.asyncio
async def test_worker_repeat_sweep_idempotency_zero_duplicate_notifications(
    db_session: AsyncSession, seller: User, buyer1: User, active_auction: Auction
):
    service = AuctionService(db_session)
    await service.place_bid(
        buyer1,
        active_auction.auction_id,
        PlaceBidRequest(amount=Decimal("220000")),
    )
    future_time = active_auction.ends_at + timedelta(seconds=10)

    # First close
    auc1 = await service.close_single_auction_if_expired(active_auction.auction_id, future_time)
    assert auc1.status == AuctionStatus.ENDED.value

    # Snapshot notification count
    res1 = await db_session.execute(
        select(Notification).where(Notification.ref_id == active_auction.auction_id)
    )
    count1 = len(res1.scalars().all())

    # Second close (simulating repeat worker sweep)
    auc2 = await service.close_single_auction_if_expired(active_auction.auction_id, future_time)
    assert auc2.status == AuctionStatus.ENDED.value

    # Verify count has NOT changed
    res2 = await db_session.execute(
        select(Notification).where(Notification.ref_id == active_auction.auction_id)
    )
    count2 = len(res2.scalars().all())
    assert count1 == count2, "Repeat sweep created duplicate notifications!"


@pytest.mark.asyncio
async def test_concurrent_close_idempotency(
    db_session: AsyncSession, seller: User, buyer1: User, active_auction: Auction
):
    service = AuctionService(db_session)
    await service.place_bid(
        buyer1,
        active_auction.auction_id,
        PlaceBidRequest(amount=Decimal("220000")),
    )
    future_time = active_auction.ends_at + timedelta(seconds=10)

    # Attempt A: performs the transition to ENDED
    auc_a = await service.close_single_auction_if_expired(active_auction.auction_id, future_time)
    assert auc_a.status == AuctionStatus.ENDED.value

    # Attempt B: observes already ENDED and is a no-op
    auc_b = await service.close_single_auction_if_expired(active_auction.auction_id, future_time)
    assert auc_b.status == AuctionStatus.ENDED.value

    # Check that exactly 1 AUCTION_ENDED and 1 AUCTION_WON were generated
    res = await db_session.execute(
        select(Notification).where(
            Notification.ref_id == active_auction.auction_id,
            Notification.type.in_([NotificationType.AUCTION_ENDED.value, NotificationType.AUCTION_WON.value]),
        )
    )
    notifs = res.scalars().all()
    seller_ended = [n for n in notifs if n.type == NotificationType.AUCTION_ENDED.value]
    winner_won = [n for n in notifs if n.type == NotificationType.AUCTION_WON.value]

    assert len(seller_ended) == 1
    assert len(winner_won) == 1


@pytest.mark.asyncio
async def test_seller_cancel_auction_creates_zero_ended_notifications(
    db_session: AsyncSession, seller: User, active_auction: Auction
):
    service = AuctionService(db_session)

    cancelled = await service.cancel_auction(seller, active_auction.auction_id)
    assert cancelled.status == AuctionStatus.CANCELLED.value

    # Verify zero AUCTION_ENDED or AUCTION_WON notifications
    res = await db_session.execute(
        select(Notification).where(
            Notification.ref_id == active_auction.auction_id,
            Notification.type.in_([NotificationType.AUCTION_ENDED.value, NotificationType.AUCTION_WON.value]),
        )
    )
    assert len(res.scalars().all()) == 0


@pytest.mark.asyncio
async def test_independent_realtime_failure_isolation_on_bid(
    db_session: AsyncSession, seller: User, buyer1: User, buyer2: User, active_auction: Auction
):
    service = AuctionService(db_session)
    await service.place_bid(
        buyer1,
        active_auction.auction_id,
        PlaceBidRequest(amount=Decimal("200000")),
    )

    # When publish_auction_event fails, targeted user notifications must STILL be published
    with patch("app.modules.auctions.service.publish_auction_event", side_effect=Exception("Redis publish error")) as mock_pub_auc, \
         patch("app.modules.auctions.service.publish_user_event", new_callable=AsyncMock) as mock_pub_user:

        bid = await service.place_bid(
            buyer2,
            active_auction.auction_id,
            PlaceBidRequest(amount=Decimal("240000")),
        )
        assert bid.amount == Decimal("240000")

        # Public broadcast failed
        mock_pub_auc.assert_awaited_once()

        # But targeted user publications for seller and displaced buyer1 were STILL executed
        user_ids = [c[0][0] for c in mock_pub_user.call_args_list]
        assert seller.user_id in user_ids
        assert buyer1.user_id in user_ids

        # DB notifications remain committed and intact
        res = await db_session.execute(
            select(Notification).where(Notification.ref_id == active_auction.auction_id)
        )
        assert len(res.scalars().all()) == 3


@pytest.mark.asyncio
async def test_independent_realtime_failure_isolation_between_recipients(
    db_session: AsyncSession, seller: User, buyer1: User, buyer2: User, active_auction: Auction
):
    service = AuctionService(db_session)
    await service.place_bid(
        buyer1,
        active_auction.auction_id,
        PlaceBidRequest(amount=Decimal("200000")),
    )

    # When seller realtime publication fails, displaced bidder publication must STILL be executed
    async def mock_publish_with_seller_failure(user_id, event_data):
        if user_id == seller.user_id:
            raise Exception("Seller WebSocket connection dropped")

    with patch("app.modules.auctions.service.publish_user_event", side_effect=mock_publish_with_seller_failure) as mock_pub_user:
        bid = await service.place_bid(
            buyer2,
            active_auction.auction_id,
            PlaceBidRequest(amount=Decimal("260000")),
        )
        assert bid.amount == Decimal("260000")

        # Verify mock was called for both seller and buyer1 (seller failure did not abort buyer1!)
        called_user_ids = [c[0][0] for c in mock_pub_user.call_args_list]
        assert seller.user_id in called_user_ids
        assert buyer1.user_id in called_user_ids

        # DB rows remain fully committed
        res = await db_session.execute(
            select(Notification).where(
                Notification.ref_id == active_auction.auction_id,
                Notification.type == NotificationType.AUCTION_OUTBID.value,
            )
        )
        outbids = res.scalars().all()
        assert len(outbids) == 1
        assert outbids[0].user_id == buyer1.user_id
