from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.categories.models import Category
from app.modules.notifications.models import Notification, NotificationType
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
from app.modules.products.models import ListingType, Product, ProductStatus
from app.modules.users.models import User, UserAuthIdentity, UserRole, UserStatus


@pytest_asyncio.fixture(autouse=True)
async def clean_notifications(db_session: AsyncSession):
    await db_session.execute(delete(Notification))
    await db_session.commit()
    yield
    await db_session.execute(delete(Notification))
    await db_session.commit()


@pytest_asyncio.fixture
async def sample_category(db_session: AsyncSession) -> Category:
    cat = Category(
        name="Đồ Công Nghệ",
        slug=f"do-cong-nghe-{uuid4().hex[:6]}",
        is_deleted=False,
    )
    db_session.add(cat)
    await db_session.commit()
    return cat


@pytest_asyncio.fixture
async def seller(db_session: AsyncSession) -> User:
    user = User(
        email=f"seller_{uuid4().hex[:6]}@ptit.edu.vn",
        full_name="Seller User",
        role=UserRole.STUDENT.value,
        status=UserStatus.ACTIVE.value,
        bank_bin="970422",
        bank_account_number="123456789",
        bank_account_name="NGUYEN VAN BAN",
    )
    db_session.add(user)
    await db_session.flush()
    identity = UserAuthIdentity(
        user_id=user.user_id,
        provider="FIREBASE",
        provider_uid=f"uid_seller_{user.user_id}",
    )
    db_session.add(identity)
    await db_session.commit()
    return user


@pytest_asyncio.fixture
async def buyer(db_session: AsyncSession) -> User:
    user = User(
        email=f"buyer_{uuid4().hex[:6]}@ptit.edu.vn",
        full_name="Buyer User",
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
    await db_session.commit()
    return user


@pytest_asyncio.fixture
async def sample_product(
    db_session: AsyncSession, seller: User, sample_category: Category
) -> Product:
    prod = Product(
        seller_id=seller.user_id,
        category_id=sample_category.category_id,
        title="Bàn phím cơ không dây",
        description="Bàn phím cơ Bluetooth",
        listing_type=ListingType.FIXED_PRICE.value,
        price=Decimal("200000"),
        stock=5,
        reserved_stock=0,
        status=ProductStatus.AVAILABLE.value,
        approval_status="APPROVED",
        is_deleted=False,
    )
    db_session.add(prod)
    await db_session.commit()
    return prod


@pytest_asyncio.fixture
async def sample_order(
    db_session: AsyncSession, buyer: User, seller: User, sample_product: Product
) -> Order:
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    sample_product.reserved_stock += 1
    await db_session.flush()

    order = Order(
        order_code=f"ORD-NOTIF-{uuid4().hex[:6].upper()}",
        buyer_id=buyer.user_id,
        seller_id=seller.user_id,
        status=OrderStatus.PENDING.value,
        payment_method=PaymentMethod.CASH_ON_MEETUP.value,
        payment_status=PaymentStatus.UNPAID,
        fulfillment_method=FulfillmentMethod.MEETUP.value,
        meetup_place="Cổng trường PTIT",
        contact_name="Buyer User",
        contact_phone="0912345678",
        total_amount=Decimal("200000"),
        auto_cancel_at=now_utc + timedelta(hours=24),
    )
    db_session.add(order)
    await db_session.flush()

    item = OrderItem(
        order_id=order.order_id,
        product_id=sample_product.product_id,
        product_title=sample_product.title,
        quantity=1,
        price_at_purchase=Decimal("200000"),
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(order)
    return order


# ============================================================================
# 1. ORDER CONFIRMED
# ============================================================================
@pytest.mark.asyncio
async def test_seller_confirms_order_notifies_buyer(
    db_session: AsyncSession, seller: User, buyer: User, sample_order: Order
):
    service = OrderService(db_session)
    req = ConfirmOrderRequest(payment_note="Hẹn gặp đúng giờ nhé")

    with patch("app.modules.orders.service.publish_order_updated", new_callable=AsyncMock) as mock_order_ws, \
         patch("app.modules.orders.service.safe_publish_user_notification", new_callable=AsyncMock) as mock_notif_ws:
        updated = await service.confirm_order(sample_order.order_id, seller, req)
        assert updated.status == OrderStatus.CONFIRMED.value

    # Verify Buyer received 1 ORDER_STATUS notification
    stmt = select(Notification).where(
        Notification.user_id == buyer.user_id,
        Notification.type == NotificationType.ORDER_STATUS.value,
    )
    res = await db_session.execute(stmt)
    buyer_notifs = res.scalars().all()
    assert len(buyer_notifs) == 1
    assert buyer_notifs[0].title == "Đơn hàng đã được xác nhận"
    assert sample_order.order_code in buyer_notifs[0].body
    assert buyer_notifs[0].ref_type == "ORDER"
    assert buyer_notifs[0].ref_id == sample_order.order_id

    # Verify Seller received 0 notifications (actor exclusion rule)
    stmt_seller = select(Notification).where(
        Notification.user_id == seller.user_id,
        Notification.type == NotificationType.ORDER_STATUS.value,
    )
    res_seller = await db_session.execute(stmt_seller)
    seller_notifs = res_seller.scalars().all()
    assert len(seller_notifs) == 0

    # Realtime publish attempted for buyer
    mock_notif_ws.assert_awaited_once()
    assert mock_notif_ws.await_args[0][0] == buyer.user_id


@pytest.mark.asyncio
async def test_repeated_order_confirmation_preserves_error_semantics_zero_new_notifications(
    db_session: AsyncSession, seller: User, buyer: User, sample_order: Order
):
    service = OrderService(db_session)
    req = ConfirmOrderRequest(payment_note="Xác nhận 1")
    await service.confirm_order(sample_order.order_id, seller, req)

    # Repeat confirm_order should raise 400 Bad Request per existing behavior
    with pytest.raises(HTTPException) as exc_info:
        await service.confirm_order(sample_order.order_id, seller, req)
    assert exc_info.value.status_code == 400

    # Notification count remains exactly 1
    stmt = select(Notification).where(
        Notification.user_id == buyer.user_id,
        Notification.type == NotificationType.ORDER_STATUS.value,
    )
    res = await db_session.execute(stmt)
    assert len(res.scalars().all()) == 1


# ============================================================================
# 2. PAYMENT RECEIPT SUBMITTED
# ============================================================================
@pytest.mark.asyncio
async def test_buyer_uploads_payment_receipt_notifies_seller(
    db_session: AsyncSession, seller: User, buyer: User, sample_order: Order
):
    service = OrderService(db_session)
    # Set to CONFIRMED + BANK_TRANSFER
    sample_order.status = OrderStatus.CONFIRMED.value
    sample_order.payment_method = PaymentMethod.BANK_TRANSFER.value
    sample_order.payment_status = PaymentStatus.UNPAID
    sample_order.payment_bank_bin = seller.bank_bin
    sample_order.payment_bank_account_number = seller.bank_account_number
    sample_order.payment_bank_account_name = seller.bank_account_name
    await db_session.commit()

    mock_upload = {"secure_url": "https://res.cloudinary.com/demo/receipt.jpg"}
    with patch("app.modules.orders.service.upload_order_receipt", return_value=mock_upload), \
         patch("app.modules.orders.service.publish_order_updated", new_callable=AsyncMock), \
         patch("app.modules.orders.service.safe_publish_user_notification", new_callable=AsyncMock) as mock_notif_ws:
        await service.upload_payment_receipt(
            order_id=sample_order.order_id,
            buyer=buyer,
            file_bytes=b"fake_image_bytes",
            content_type="image/jpeg",
        )

    # Verify Seller received 1 ORDER_STATUS notification
    stmt = select(Notification).where(
        Notification.user_id == seller.user_id,
        Notification.type == NotificationType.ORDER_STATUS.value,
    )
    res = await db_session.execute(stmt)
    seller_notifs = res.scalars().all()
    assert len(seller_notifs) == 1
    assert seller_notifs[0].title == "Người mua đã gửi biên nhận"
    assert sample_order.order_code in seller_notifs[0].body
    assert seller_notifs[0].ref_type == "ORDER"
    assert seller_notifs[0].ref_id == sample_order.order_id

    # Buyer received 0 notifications (actor exclusion rule)
    stmt_buyer = select(Notification).where(
        Notification.user_id == buyer.user_id,
        Notification.type == NotificationType.ORDER_STATUS.value,
    )
    res_buyer = await db_session.execute(stmt_buyer)
    assert len(res_buyer.scalars().all()) == 0

    mock_notif_ws.assert_awaited_once()
    assert mock_notif_ws.await_args[0][0] == seller.user_id


@pytest.mark.asyncio
async def test_failed_receipt_upload_creates_zero_notifications(
    db_session: AsyncSession, seller: User, buyer: User, sample_order: Order
):
    service = OrderService(db_session)
    sample_order.status = OrderStatus.CONFIRMED.value
    sample_order.payment_method = PaymentMethod.BANK_TRANSFER.value
    await db_session.commit()

    # Invalid MIME type raises 400
    with pytest.raises(HTTPException) as exc_info:
        await service.upload_payment_receipt(
            order_id=sample_order.order_id,
            buyer=buyer,
            file_bytes=b"fake_pdf",
            content_type="application/pdf",
        )
    assert exc_info.value.status_code == 400

    # 0 notifications
    stmt = select(Notification).where(Notification.type == NotificationType.ORDER_STATUS.value)
    res = await db_session.execute(stmt)
    assert len(res.scalars().all()) == 0


# ============================================================================
# 3. PAYMENT CONFIRMED
# ============================================================================
@pytest.mark.asyncio
async def test_seller_confirms_payment_notifies_buyer(
    db_session: AsyncSession, seller: User, buyer: User, sample_order: Order
):
    service = OrderService(db_session)
    sample_order.status = OrderStatus.CONFIRMED.value
    sample_order.payment_method = PaymentMethod.CASH_ON_MEETUP.value
    sample_order.payment_status = PaymentStatus.UNPAID
    await db_session.commit()

    with patch("app.modules.orders.service.publish_order_updated", new_callable=AsyncMock), \
         patch("app.modules.orders.service.safe_publish_user_notification", new_callable=AsyncMock) as mock_notif_ws:
        await service.confirm_payment(sample_order.order_id, seller)

    # Verify Buyer received 1 ORDER_STATUS notification
    stmt = select(Notification).where(
        Notification.user_id == buyer.user_id,
        Notification.type == NotificationType.ORDER_STATUS.value,
    )
    res = await db_session.execute(stmt)
    buyer_notifs = res.scalars().all()
    assert len(buyer_notifs) == 1
    assert buyer_notifs[0].title == "Thanh toán đã được xác nhận"
    assert sample_order.order_code in buyer_notifs[0].body

    mock_notif_ws.assert_awaited_once()
    assert mock_notif_ws.await_args[0][0] == buyer.user_id


@pytest.mark.asyncio
async def test_repeated_payment_confirmation_preserves_idempotent_semantics_zero_duplicate_notifications(
    db_session: AsyncSession, seller: User, buyer: User, sample_order: Order
):
    service = OrderService(db_session)
    sample_order.status = OrderStatus.CONFIRMED.value
    sample_order.payment_method = PaymentMethod.CASH_ON_MEETUP.value
    sample_order.payment_status = PaymentStatus.UNPAID
    await db_session.commit()

    # First call succeeds and notifies
    await service.confirm_payment(sample_order.order_id, seller)

    # Second call returns idempotently per existing service logic
    await service.confirm_payment(sample_order.order_id, seller)

    # Exactly 1 notification exists
    stmt = select(Notification).where(
        Notification.user_id == buyer.user_id,
        Notification.type == NotificationType.ORDER_STATUS.value,
    )
    res = await db_session.execute(stmt)
    assert len(res.scalars().all()) == 1


# ============================================================================
# 4. ORDER DELIVERING (SHIPPING ONLY)
# ============================================================================
@pytest.mark.asyncio
async def test_seller_marks_delivering_notifies_buyer(
    db_session: AsyncSession, seller: User, buyer: User, sample_order: Order
):
    service = OrderService(db_session)
    sample_order.status = OrderStatus.CONFIRMED.value
    sample_order.fulfillment_method = FulfillmentMethod.SHIPPING.value
    sample_order.shipping_address = "123 Đường Bưu Điện"
    sample_order.payment_method = PaymentMethod.CASH_ON_MEETUP.value
    sample_order.payment_status = PaymentStatus.PAID
    sample_order.paid_confirmed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db_session.commit()

    with patch("app.modules.orders.service.publish_order_updated", new_callable=AsyncMock), \
         patch("app.modules.orders.service.safe_publish_user_notification", new_callable=AsyncMock) as mock_notif_ws:
        await service.mark_delivering(sample_order.order_id, seller)

    stmt = select(Notification).where(
        Notification.user_id == buyer.user_id,
        Notification.type == NotificationType.ORDER_STATUS.value,
    )
    res = await db_session.execute(stmt)
    buyer_notifs = res.scalars().all()
    assert len(buyer_notifs) == 1
    assert buyer_notifs[0].title == "Đơn hàng đang được giao"
    assert sample_order.order_code in buyer_notifs[0].body

    mock_notif_ws.assert_awaited_once()
    assert mock_notif_ws.await_args[0][0] == buyer.user_id


@pytest.mark.asyncio
async def test_mark_delivering_invalid_fulfillment_preserves_error_and_creates_zero_notifications(
    db_session: AsyncSession, seller: User, sample_order: Order
):
    service = OrderService(db_session)
    sample_order.status = OrderStatus.CONFIRMED.value
    sample_order.fulfillment_method = FulfillmentMethod.MEETUP.value
    await db_session.commit()

    # MEETUP orders cannot transition to DELIVERING
    with pytest.raises(HTTPException) as exc_info:
        await service.mark_delivering(sample_order.order_id, seller)
    assert exc_info.value.status_code == 400

    stmt = select(Notification).where(Notification.type == NotificationType.ORDER_STATUS.value)
    res = await db_session.execute(stmt)
    assert len(res.scalars().all()) == 0


# ============================================================================
# 5. ORDER COMPLETED
# ============================================================================
@pytest.mark.asyncio
async def test_buyer_completes_order_notifies_seller(
    db_session: AsyncSession, seller: User, buyer: User, sample_order: Order
):
    service = OrderService(db_session)
    sample_order.status = OrderStatus.CONFIRMED.value
    sample_order.fulfillment_method = FulfillmentMethod.MEETUP.value
    sample_order.payment_status = PaymentStatus.PAID
    sample_order.paid_confirmed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db_session.commit()

    with patch("app.modules.orders.service.publish_order_updated", new_callable=AsyncMock), \
         patch("app.modules.orders.service.safe_publish_user_notification", new_callable=AsyncMock) as mock_notif_ws:
        await service.complete_order(sample_order.order_id, buyer)

    stmt = select(Notification).where(
        Notification.user_id == seller.user_id,
        Notification.type == NotificationType.ORDER_STATUS.value,
    )
    res = await db_session.execute(stmt)
    seller_notifs = res.scalars().all()
    assert len(seller_notifs) == 1
    assert seller_notifs[0].title == "Đơn hàng đã hoàn tất"
    assert sample_order.order_code in seller_notifs[0].body

    # Buyer gets 0
    stmt_buyer = select(Notification).where(Notification.user_id == buyer.user_id)
    res_buyer = await db_session.execute(stmt_buyer)
    assert len(res_buyer.scalars().all()) == 0

    mock_notif_ws.assert_awaited_once()
    assert mock_notif_ws.await_args[0][0] == seller.user_id


@pytest.mark.asyncio
async def test_seller_completes_order_notifies_buyer(
    db_session: AsyncSession, seller: User, buyer: User, sample_order: Order
):
    service = OrderService(db_session)
    sample_order.status = OrderStatus.CONFIRMED.value
    sample_order.fulfillment_method = FulfillmentMethod.MEETUP.value
    sample_order.payment_status = PaymentStatus.PAID
    sample_order.paid_confirmed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db_session.commit()

    with patch("app.modules.orders.service.publish_order_updated", new_callable=AsyncMock), \
         patch("app.modules.orders.service.safe_publish_user_notification", new_callable=AsyncMock) as mock_notif_ws:
        await service.complete_order(sample_order.order_id, seller)

    stmt = select(Notification).where(
        Notification.user_id == buyer.user_id,
        Notification.type == NotificationType.ORDER_STATUS.value,
    )
    res = await db_session.execute(stmt)
    buyer_notifs = res.scalars().all()
    assert len(buyer_notifs) == 1
    assert buyer_notifs[0].title == "Đơn hàng đã hoàn tất"
    assert sample_order.order_code in buyer_notifs[0].body

    # Seller gets 0
    stmt_seller = select(Notification).where(Notification.user_id == seller.user_id)
    res_seller = await db_session.execute(stmt_seller)
    assert len(res_seller.scalars().all()) == 0

    mock_notif_ws.assert_awaited_once()
    assert mock_notif_ws.await_args[0][0] == buyer.user_id


@pytest.mark.asyncio
async def test_repeated_complete_order_preserves_error_semantics_zero_duplicate_notifications(
    db_session: AsyncSession, seller: User, buyer: User, sample_order: Order
):
    service = OrderService(db_session)
    sample_order.status = OrderStatus.CONFIRMED.value
    sample_order.fulfillment_method = FulfillmentMethod.MEETUP.value
    sample_order.payment_status = PaymentStatus.PAID
    sample_order.paid_confirmed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db_session.commit()

    await service.complete_order(sample_order.order_id, buyer)

    # Calling complete_order again raises 400
    with pytest.raises(HTTPException) as exc_info:
        await service.complete_order(sample_order.order_id, buyer)
    assert exc_info.value.status_code == 400

    # Notification count is still 1
    stmt = select(Notification).where(Notification.type == NotificationType.ORDER_STATUS.value)
    res = await db_session.execute(stmt)
    assert len(res.scalars().all()) == 1


# ============================================================================
# 6. ORDER CANCELLED (MANUAL)
# ============================================================================
@pytest.mark.asyncio
async def test_buyer_cancels_order_notifies_seller(
    db_session: AsyncSession, seller: User, buyer: User, sample_order: Order
):
    service = OrderService(db_session)
    req = CancelOrderRequest(cancel_reason="Tôi bận đột xuất")

    with patch("app.modules.orders.service.publish_order_updated", new_callable=AsyncMock), \
         patch("app.modules.orders.service.safe_publish_user_notification", new_callable=AsyncMock) as mock_notif_ws:
        await service.cancel_order(sample_order.order_id, buyer, req)

    stmt = select(Notification).where(
        Notification.user_id == seller.user_id,
        Notification.type == NotificationType.ORDER_STATUS.value,
    )
    res = await db_session.execute(stmt)
    seller_notifs = res.scalars().all()
    assert len(seller_notifs) == 1
    assert seller_notifs[0].title == "Đơn hàng đã bị hủy"
    assert "Người mua đã hủy đơn" in seller_notifs[0].body
    assert sample_order.order_code in seller_notifs[0].body
    # Sensitive cancel_reason is NOT leaked into body
    assert "Tôi bận đột xuất" not in seller_notifs[0].body

    # Buyer gets 0
    stmt_buyer = select(Notification).where(Notification.user_id == buyer.user_id)
    res_buyer = await db_session.execute(stmt_buyer)
    assert len(res_buyer.scalars().all()) == 0

    mock_notif_ws.assert_awaited_once()
    assert mock_notif_ws.await_args[0][0] == seller.user_id


@pytest.mark.asyncio
async def test_seller_cancels_order_notifies_buyer(
    db_session: AsyncSession, seller: User, buyer: User, sample_order: Order
):
    service = OrderService(db_session)
    req = CancelOrderRequest(cancel_reason="Hết hàng đột xuất")

    with patch("app.modules.orders.service.publish_order_updated", new_callable=AsyncMock), \
         patch("app.modules.orders.service.safe_publish_user_notification", new_callable=AsyncMock) as mock_notif_ws:
        await service.cancel_order(sample_order.order_id, seller, req)

    stmt = select(Notification).where(
        Notification.user_id == buyer.user_id,
        Notification.type == NotificationType.ORDER_STATUS.value,
    )
    res = await db_session.execute(stmt)
    buyer_notifs = res.scalars().all()
    assert len(buyer_notifs) == 1
    assert buyer_notifs[0].title == "Đơn hàng đã bị hủy"
    assert "Người bán đã hủy đơn" in buyer_notifs[0].body
    assert sample_order.order_code in buyer_notifs[0].body
    assert "Hết hàng đột xuất" not in buyer_notifs[0].body

    # Seller gets 0
    stmt_seller = select(Notification).where(Notification.user_id == seller.user_id)
    res_seller = await db_session.execute(stmt_seller)
    assert len(res_seller.scalars().all()) == 0

    mock_notif_ws.assert_awaited_once()
    assert mock_notif_ws.await_args[0][0] == buyer.user_id


@pytest.mark.asyncio
async def test_repeated_cancel_order_preserves_idempotent_semantics_zero_duplicate_notifications(
    db_session: AsyncSession, seller: User, buyer: User, sample_order: Order
):
    service = OrderService(db_session)
    req = CancelOrderRequest(cancel_reason="Hủy đơn")

    await service.cancel_order(sample_order.order_id, buyer, req)

    # Repeat cancel call
    await service.cancel_order(sample_order.order_id, buyer, req)

    # Exactly 1 notification exists
    stmt = select(Notification).where(Notification.type == NotificationType.ORDER_STATUS.value)
    res = await db_session.execute(stmt)
    assert len(res.scalars().all()) == 1


# ============================================================================
# 7. SYSTEM AUTO-CANCEL
# ============================================================================
@pytest.mark.asyncio
async def test_system_auto_cancel_notifies_both_buyer_and_seller_in_single_transaction(
    db_session: AsyncSession, seller: User, buyer: User, sample_order: Order
):
    service = OrderService(db_session)
    # Expire order
    sample_order.auto_cancel_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
    await db_session.commit()

    with patch("app.modules.orders.service.publish_order_updated", new_callable=AsyncMock), \
         patch("app.modules.orders.service.safe_publish_user_notification", new_callable=AsyncMock) as mock_notif_ws:
        res = await service.auto_cancel_single_order(sample_order.order_id)
        assert res is True

    # Both Buyer and Seller must have 1 notification each
    stmt_b = select(Notification).where(
        Notification.user_id == buyer.user_id,
        Notification.type == NotificationType.ORDER_STATUS.value,
    )
    res_b = await db_session.execute(stmt_b)
    b_notifs = res_b.scalars().all()
    assert len(b_notifs) == 1
    assert b_notifs[0].title == "Đơn hàng đã tự động hủy"
    assert sample_order.order_code in b_notifs[0].body
    assert b_notifs[0].ref_type == "ORDER"
    assert b_notifs[0].ref_id == sample_order.order_id

    stmt_s = select(Notification).where(
        Notification.user_id == seller.user_id,
        Notification.type == NotificationType.ORDER_STATUS.value,
    )
    res_s = await db_session.execute(stmt_s)
    s_notifs = res_s.scalars().all()
    assert len(s_notifs) == 1
    assert s_notifs[0].title == "Đơn hàng đã tự động hủy"
    assert sample_order.order_code in s_notifs[0].body
    assert s_notifs[0].ref_type == "ORDER"
    assert s_notifs[0].ref_id == sample_order.order_id

    # Realtime was dispatched independently to both
    assert mock_notif_ws.await_count == 2
    recipients = {call[0][0] for call in mock_notif_ws.await_args_list}
    assert recipients == {buyer.user_id, seller.user_id}


@pytest.mark.asyncio
async def test_repeated_system_auto_cancel_sweep_creates_zero_duplicate_notifications(
    db_session: AsyncSession, seller: User, buyer: User, sample_order: Order
):
    service = OrderService(db_session)
    sample_order.auto_cancel_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
    await db_session.commit()

    res1 = await service.auto_cancel_single_order(sample_order.order_id)
    assert res1 is True

    # Repeat sweep
    res2 = await service.auto_cancel_single_order(sample_order.order_id)
    assert res2 is False

    # Total notifications still 2 (1 for buyer, 1 for seller)
    stmt = select(Notification).where(Notification.type == NotificationType.ORDER_STATUS.value)
    res = await db_session.execute(stmt)
    assert len(res.scalars().all()) == 2


# ============================================================================
# 8. TRANSACTION TERMS UPDATED (EVENT 8)
# ============================================================================
@pytest.mark.asyncio
async def test_update_transaction_terms_material_change_notifies_buyer(
    db_session: AsyncSession, seller: User, buyer: User, sample_order: Order
):
    service = OrderService(db_session)
    req = UpdateOrderTransactionTermsRequest(
        meetup_place="Cổng số 2 PTIT",
        payment_note="Đổi địa điểm hẹn",
    )

    with patch("app.modules.orders.service.publish_order_updated", new_callable=AsyncMock), \
         patch("app.modules.orders.service.safe_publish_user_notification", new_callable=AsyncMock) as mock_notif_ws:
        await service.update_transaction_terms(sample_order.order_id, seller, req)

    stmt = select(Notification).where(
        Notification.user_id == buyer.user_id,
        Notification.type == NotificationType.ORDER_STATUS.value,
    )
    res = await db_session.execute(stmt)
    buyer_notifs = res.scalars().all()
    assert len(buyer_notifs) == 1
    assert buyer_notifs[0].title == "Điều khoản đơn hàng đã được cập nhật"
    assert sample_order.order_code in buyer_notifs[0].body

    mock_notif_ws.assert_awaited_once()
    assert mock_notif_ws.await_args[0][0] == buyer.user_id


@pytest.mark.asyncio
async def test_update_transaction_terms_noop_creates_zero_notifications(
    db_session: AsyncSession, seller: User, buyer: User, sample_order: Order
):
    service = OrderService(db_session)
    # PATCH with the exact same values
    req = UpdateOrderTransactionTermsRequest(
        meetup_place=sample_order.meetup_place,
    )

    with patch("app.modules.orders.service.publish_order_updated", new_callable=AsyncMock), \
         patch("app.modules.orders.service.safe_publish_user_notification", new_callable=AsyncMock) as mock_notif_ws:
        await service.update_transaction_terms(sample_order.order_id, seller, req)

    # 0 notifications
    stmt = select(Notification).where(Notification.type == NotificationType.ORDER_STATUS.value)
    res = await db_session.execute(stmt)
    assert len(res.scalars().all()) == 0
    mock_notif_ws.assert_not_awaited()


# ============================================================================
# 9. ATOMICITY & REALTIME ISOLATION
# ============================================================================
@pytest.mark.asyncio
async def test_transaction_atomicity_pre_commit_failure_rolls_back_everything(
    db_session: AsyncSession, seller: User, buyer: User, sample_order: Order
):
    order_id = sample_order.order_id
    service = OrderService(db_session)
    req = ConfirmOrderRequest(payment_note="Test atomicity")

    with patch.object(db_session, "commit", side_effect=RuntimeError("Forced DB commit error")):
        with pytest.raises(RuntimeError, match="Forced DB commit error"):
            await service.confirm_order(order_id, seller, req)

    # Roll back session to inspect clean state
    await db_session.rollback()

    # Re-fetch order: must still be PENDING
    fresh_order = await db_session.get(Order, order_id)
    assert fresh_order is not None
    assert fresh_order.status == OrderStatus.PENDING.value

    # 0 notifications committed
    stmt = select(Notification).where(Notification.type == NotificationType.ORDER_STATUS.value)
    res = await db_session.execute(stmt)
    assert len(res.scalars().all()) == 0


@pytest.mark.asyncio
async def test_realtime_publish_failure_does_not_rollback_db(
    db_session: AsyncSession, seller: User, buyer: User, sample_order: Order
):
    service = OrderService(db_session)
    req = ConfirmOrderRequest(payment_note="Test ws isolation")

    # Mock publish_user_event to fail
    with patch("app.modules.orders.service.publish_order_updated", side_effect=Exception("WS order update broke")), \
         patch("app.modules.orders.websocket.publish_user_event", side_effect=Exception("Redis publish broke")):
        updated = await service.confirm_order(sample_order.order_id, seller, req)
        assert updated.status == OrderStatus.CONFIRMED.value

    # DB state and notification MUST still be committed
    fresh_order = await db_session.get(Order, sample_order.order_id)
    assert fresh_order is not None
    assert fresh_order.status == OrderStatus.CONFIRMED.value

    stmt = select(Notification).where(Notification.type == NotificationType.ORDER_STATUS.value)
    res = await db_session.execute(stmt)
    assert len(res.scalars().all()) == 1


@pytest.mark.asyncio
async def test_auto_cancel_realtime_publish_isolation_between_recipients(
    db_session: AsyncSession, seller: User, buyer: User, sample_order: Order
):
    service = OrderService(db_session)
    sample_order.auto_cancel_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
    await db_session.commit()

    published_users = []

    async def mock_publish_user(user_id, event):
        if user_id == buyer.user_id:
            raise RuntimeError("Buyer realtime network failure")
        published_users.append(user_id)

    with patch("app.modules.orders.service.publish_order_updated", new_callable=AsyncMock), \
         patch("app.modules.orders.service.publish_user_event", side_effect=mock_publish_user):
        res = await service.auto_cancel_single_order(sample_order.order_id)
        assert res is True

    # Even though buyer publish failed, safe_publish_user_notification caught it,
    # and seller publish was still executed
    assert seller.user_id in published_users


# ============================================================================
# 10. CROSS-PHASE REGRESSION: ORDER CREATION PRODUCES ONLY NEW_ORDER
# ============================================================================
@pytest.mark.asyncio
async def test_order_creation_produces_only_new_order_never_order_status(
    db_session: AsyncSession, seller: User, buyer: User, sample_product: Product
):
    service = OrderService(db_session)
    req = CreateOrderRequest(
        product_id=sample_product.product_id,
        quantity=1,
        fulfillment_method=FulfillmentMethod.MEETUP,
        meetup_place="Sảnh A1",
        contact_name="Buyer Test",
        contact_phone="0911222333",
        payment_method=PaymentMethod.CASH_ON_MEETUP,
    )

    with patch("app.modules.orders.service.publish_order_created", new_callable=AsyncMock), \
         patch("app.modules.orders.service.safe_publish_user_notification", new_callable=AsyncMock):
        created_order = await service.create_direct_order(buyer, req)

    # Exactly 1 NEW_ORDER notification for Seller
    stmt_new = select(Notification).where(
        Notification.user_id == seller.user_id,
        Notification.type == NotificationType.NEW_ORDER.value,
    )
    res_new = await db_session.execute(stmt_new)
    assert len(res_new.scalars().all()) == 1

    # ZERO ORDER_STATUS notifications exist anywhere
    stmt_status = select(Notification).where(
        Notification.type == NotificationType.ORDER_STATUS.value,
    )
    res_status = await db_session.execute(stmt_status)
    assert len(res_status.scalars().all()) == 0
