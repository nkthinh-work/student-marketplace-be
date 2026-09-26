from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.dependencies import authenticate_user_token
from app.modules.auctions.models import Auction, AuctionStatus
from app.modules.auctions.schemas import WinnerCheckoutRequest
from app.modules.auctions.service import AuctionService
from app.modules.categories.models import Category
from app.modules.orders.models import (
    FulfillmentMethod,
    Order,
    OrderItem,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
)
from app.modules.orders.schemas import (
    CancelOrderRequest,
    ConfirmOrderRequest,
    CreateOrderRequest,
    UpdateOrderTransactionTermsRequest,
)
from app.modules.orders.service import OrderService
from app.modules.orders.websocket import (
    UserConnectionManager,
    publish_auction_winner_checked_out,
    publish_order_created,
    publish_order_updated,
    publish_user_event,
    user_ws_manager,
)
from app.modules.products.models import ListingType, Product, ProductStatus
from app.modules.users.models import User, UserAuthIdentity, UserRole, UserStatus


@pytest_asyncio.fixture
async def sample_category(db_session: AsyncSession) -> Category:
    cat = Category(
        name="Đồ điện tử",
        slug=f"do-dien-tu-{uuid4().hex[:6]}",
        is_deleted=False,
    )
    db_session.add(cat)
    await db_session.flush()
    return cat


@pytest_asyncio.fixture
async def seller(db_session: AsyncSession) -> User:
    user = User(
        email=f"seller_{uuid4().hex[:6]}@ptit.edu.vn",
        full_name="Seller A",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE.value,
        bank_bin="970422",
        bank_account_number="123456789",
        bank_account_name="SELLER A",
    )
    db_session.add(user)
    await db_session.flush()
    identity = UserAuthIdentity(
        user_id=user.user_id,
        provider="FIREBASE",
        provider_uid=f"uid_seller_{user.user_id}",
    )
    db_session.add(identity)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def buyer(db_session: AsyncSession) -> User:
    user = User(
        email=f"buyer_{uuid4().hex[:6]}@ptit.edu.vn",
        full_name="Buyer B",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE.value,
    )
    db_session.add(user)
    await db_session.flush()
    identity = UserAuthIdentity(
        user_id=user.user_id,
        provider="FIREBASE",
        provider_uid=f"uid_buyer_{user.user_id}",
    )
    db_session.add(identity)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def winner(db_session: AsyncSession) -> User:
    user = User(
        email=f"winner_{uuid4().hex[:6]}@ptit.edu.vn",
        full_name="Winner C",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE.value,
    )
    db_session.add(user)
    await db_session.flush()
    identity = UserAuthIdentity(
        user_id=user.user_id,
        provider="FIREBASE",
        provider_uid=f"uid_winner_{user.user_id}",
    )
    db_session.add(identity)
    await db_session.flush()
    return user


@pytest.mark.asyncio
async def test_user_connection_manager_lifecycle():
    manager = UserConnectionManager()
    ws1 = AsyncMock()
    ws2 = AsyncMock()

    # Connect user 10
    await manager.connect(10, ws1)
    assert 10 in manager._connections
    assert ws1 in manager._connections[10]

    # Connect another socket for user 10
    await manager.connect(10, ws2)
    assert len(manager._connections[10]) == 2

    # Send local event
    event = {"type": "ORDER_UPDATED", "order_id": 123}
    await manager.send_to_user_local(10, event)
    ws1.send_json.assert_awaited_once_with(event)
    ws2.send_json.assert_awaited_once_with(event)

    # Disconnect
    await manager.disconnect(10, ws1)
    assert len(manager._connections[10]) == 1
    await manager.disconnect(10, ws2)
    assert 10 not in manager._connections


@pytest.mark.asyncio
async def test_publish_order_updated_routes_only_to_participants():
    manager = UserConnectionManager()
    buyer_ws = AsyncMock()
    seller_ws = AsyncMock()
    other_ws = AsyncMock()

    await manager.connect(10, seller_ws)
    await manager.connect(20, buyer_ws)
    await manager.connect(99, other_ws)

    with patch("app.modules.orders.websocket.user_ws_manager", manager):
        await publish_order_updated(buyer_id=20, seller_id=10, order_id=555, reason="CONFIRMED")

        expected = {"type": "ORDER_UPDATED", "order_id": 555, "reason": "CONFIRMED"}
        seller_ws.send_json.assert_awaited_once_with(expected)
        buyer_ws.send_json.assert_awaited_once_with(expected)
        other_ws.send_json.assert_not_called()


@pytest.mark.asyncio
async def test_publish_order_created_routes_to_seller():
    manager = UserConnectionManager()
    seller_ws = AsyncMock()
    buyer_ws = AsyncMock()

    await manager.connect(10, seller_ws)
    await manager.connect(20, buyer_ws)

    with patch("app.modules.orders.websocket.user_ws_manager", manager):
        await publish_order_created(seller_id=10, order_id=777)

        expected = {"type": "ORDER_CREATED", "order_id": 777}
        seller_ws.send_json.assert_awaited_once_with(expected)
        buyer_ws.send_json.assert_not_called()


@pytest.mark.asyncio
async def test_publish_auction_winner_checked_out_routes_to_seller():
    manager = UserConnectionManager()
    seller_ws = AsyncMock()
    winner_ws = AsyncMock()

    await manager.connect(10, seller_ws)
    await manager.connect(30, winner_ws)

    with patch("app.modules.orders.websocket.user_ws_manager", manager):
        await publish_auction_winner_checked_out(seller_id=10, auction_id=42, order_id=888)

        expected = {"type": "AUCTION_WINNER_CHECKED_OUT", "auction_id": 42, "order_id": 888}
        seller_ws.send_json.assert_awaited_once_with(expected)
        winner_ws.send_json.assert_not_called()


@pytest.mark.asyncio
async def test_redis_failure_does_not_break_publishing():
    with patch("app.modules.orders.websocket.redis_client") as mock_redis:
        mock_redis.publish = AsyncMock(side_effect=Exception("Redis connection refused"))
        # Should not raise exception
        await publish_user_event(10, {"type": "ORDER_CREATED", "order_id": 1})


@pytest.mark.asyncio
async def test_order_service_emits_realtime_events_throughout_lifecycle(
    db_session: AsyncSession, seller: User, buyer: User, sample_category: Category
):
    prod = Product(
        seller_id=seller.user_id,
        category_id=sample_category.category_id,
        title="Bàn phím cơ Akko",
        price=Decimal("800000"),
        stock=2,
        reserved_stock=0,
        listing_type=ListingType.FIXED_PRICE.value,
        status=ProductStatus.AVAILABLE.value,
        approval_status="APPROVED",
    )
    db_session.add(prod)
    await db_session.flush()

    service = OrderService(db_session)

    # 1. Create order -> emits ORDER_CREATED to seller
    with patch("app.modules.orders.service.publish_order_created", new_callable=AsyncMock) as mock_pub_create:
        order = await service.create_direct_order(
            buyer=buyer,
            payload=CreateOrderRequest(
                product_id=prod.product_id,
                quantity=1,
                fulfillment_method=FulfillmentMethod.SHIPPING,
                payment_method=PaymentMethod.BANK_TRANSFER,
                shipping_address="123 Tran Phu, Ha Dong",
                contact_name="Nguyen Van B",
                contact_phone="0912345678",
            ),
        )
        mock_pub_create.assert_awaited_once_with(seller_id=seller.user_id, order_id=order.order_id)

    # 2. Confirm order -> emits ORDER_UPDATED with reason=CONFIRMED
    with patch("app.modules.orders.service.publish_order_updated", new_callable=AsyncMock) as mock_pub_update:
        await service.confirm_order(
            order_id=order.order_id,
            seller=seller,
            payload=ConfirmOrderRequest(payment_note="Vui lòng ghi mã đơn khi chuyển"),
        )
        mock_pub_update.assert_awaited_once_with(
            buyer_id=buyer.user_id,
            seller_id=seller.user_id,
            order_id=order.order_id,
            reason="CONFIRMED",
        )

    # 3. Upload receipt -> emits ORDER_UPDATED with reason=RECEIPT_UPLOADED
    with patch("app.modules.orders.service.upload_order_receipt", return_value={"secure_url": "https://img.jpg"}), \
         patch("app.modules.orders.service.publish_order_updated", new_callable=AsyncMock) as mock_pub_update:
        await service.upload_payment_receipt(
            order_id=order.order_id,
            buyer=buyer,
            file_bytes=b"fake_image_bytes",
            content_type="image/jpeg",
        )
        mock_pub_update.assert_awaited_once_with(
            buyer_id=buyer.user_id,
            seller_id=seller.user_id,
            order_id=order.order_id,
            reason="RECEIPT_UPLOADED",
        )

    # 4. Confirm payment -> emits ORDER_UPDATED with reason=PAYMENT_CONFIRMED
    with patch("app.modules.orders.service.publish_order_updated", new_callable=AsyncMock) as mock_pub_update:
        await service.confirm_payment(order_id=order.order_id, seller=seller)
        mock_pub_update.assert_awaited_once_with(
            buyer_id=buyer.user_id,
            seller_id=seller.user_id,
            order_id=order.order_id,
            reason="PAYMENT_CONFIRMED",
        )

    # 5. Mark delivering -> emits ORDER_UPDATED with reason=DELIVERING
    with patch("app.modules.orders.service.publish_order_updated", new_callable=AsyncMock) as mock_pub_update:
        await service.mark_delivering(order_id=order.order_id, seller=seller)
        mock_pub_update.assert_awaited_once_with(
            buyer_id=buyer.user_id,
            seller_id=seller.user_id,
            order_id=order.order_id,
            reason="DELIVERING",
        )

    # 6. Complete order -> emits ORDER_UPDATED with reason=COMPLETED
    with patch("app.modules.orders.service.publish_order_updated", new_callable=AsyncMock) as mock_pub_update:
        await service.complete_order(order_id=order.order_id, current_user=seller)
        mock_pub_update.assert_awaited_once_with(
            buyer_id=buyer.user_id,
            seller_id=seller.user_id,
            order_id=order.order_id,
            reason="COMPLETED",
        )


@pytest.mark.asyncio
async def test_order_terms_and_cancellation_emits_realtime(
    db_session: AsyncSession, seller: User, buyer: User, sample_category: Category
):
    prod = Product(
        seller_id=seller.user_id,
        category_id=sample_category.category_id,
        title="Chuột Logitech G102",
        price=Decimal("300000"),
        stock=1,
        reserved_stock=0,
        listing_type=ListingType.FIXED_PRICE.value,
        status=ProductStatus.AVAILABLE.value,
        approval_status="APPROVED",
    )
    db_session.add(prod)
    await db_session.flush()

    service = OrderService(db_session)

    order = await service.create_direct_order(
        buyer=buyer,
        payload=CreateOrderRequest(
            product_id=prod.product_id,
            quantity=1,
            fulfillment_method=FulfillmentMethod.MEETUP,
            payment_method=PaymentMethod.CASH_ON_MEETUP,
            meetup_place="Sanh A2 PTIT",
            contact_name="Nguyen Van B",
            contact_phone="0912345678",
        ),
    )

    # 1. Update terms -> emits ORDER_UPDATED with reason=TERMS_UPDATED
    with patch("app.modules.orders.service.publish_order_updated", new_callable=AsyncMock) as mock_pub_update:
        await service.update_transaction_terms(
            order_id=order.order_id,
            seller=seller,
            payload=UpdateOrderTransactionTermsRequest(
                meetup_place="Sanh A1 PTIT",
            ),
        )
        mock_pub_update.assert_awaited_once_with(
            buyer_id=buyer.user_id,
            seller_id=seller.user_id,
            order_id=order.order_id,
            reason="TERMS_UPDATED",
        )

    # 2. Cancel order -> emits ORDER_UPDATED with reason=CANCELLED
    with patch("app.modules.orders.service.publish_order_updated", new_callable=AsyncMock) as mock_pub_update:
        await service.cancel_order(
            order_id=order.order_id,
            current_user=buyer,
            payload=CancelOrderRequest(cancel_reason="Thay đổi kế hoạch"),
        )
        mock_pub_update.assert_awaited_once_with(
            buyer_id=buyer.user_id,
            seller_id=seller.user_id,
            order_id=order.order_id,
            reason="CANCELLED",
        )


@pytest.mark.asyncio
async def test_winner_checkout_emits_realtime_events_to_seller(
    db_session: AsyncSession, seller: User, winner: User, sample_category: Category
):
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    prod = Product(
        seller_id=seller.user_id,
        category_id=sample_category.category_id,
        title="iPad Air 5",
        price=Decimal("10000000"),
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
        starting_price=Decimal("10000000"),
        bid_step=Decimal("100000"),
        starts_at=now - timedelta(hours=2),
        ends_at=now - timedelta(minutes=10),
        status=AuctionStatus.ENDED.value,
        winner_id=winner.user_id,
        final_price=Decimal("11000000"),
        winner_checkout_deadline=now + timedelta(hours=23),
    )
    db_session.add(auc)
    await db_session.flush()

    service = AuctionService(db_session)

    with patch("app.modules.orders.websocket.publish_auction_winner_checked_out", new_callable=AsyncMock) as mock_pub_auc, \
         patch("app.modules.orders.websocket.publish_order_created", new_callable=AsyncMock) as mock_pub_ord:
        order = await service.winner_checkout(
            winner=winner,
            auction_id=auc.auction_id,
            payload=WinnerCheckoutRequest(
                fulfillment_method=FulfillmentMethod.MEETUP,
                payment_method=PaymentMethod.CASH_ON_MEETUP,
                meetup_place="Sanh A2 PTIT",
                contact_name="Winner C",
                contact_phone="0911223344",
            ),
        )
        mock_pub_auc.assert_awaited_once_with(
            seller_id=seller.user_id,
            auction_id=auc.auction_id,
            order_id=order.order_id,
        )
        mock_pub_ord.assert_awaited_once_with(
            seller_id=seller.user_id,
            order_id=order.order_id,
        )


@pytest.mark.asyncio
async def test_authenticate_user_token_validates_token_and_active_status(
    db_session: AsyncSession, seller: User
):
    # Valid token
    with patch("app.modules.auth.dependencies.verify_firebase_token", return_value={"uid": f"uid_seller_{seller.user_id}", "email": seller.email}):
        user = await authenticate_user_token("valid_token", db_session)
        assert user is not None
        assert user.user_id == seller.user_id

    # Banned user rejected
    seller.status = UserStatus.BANNED.value
    await db_session.flush()

    with patch("app.modules.auth.dependencies.verify_firebase_token", return_value={"uid": f"uid_seller_{seller.user_id}", "email": seller.email}):
        with pytest.raises(Exception) as exc:
            await authenticate_user_token("valid_token", db_session)
        assert "bị khóa" in str(exc.value)
