from datetime import datetime, timedelta, timezone
from decimal import Decimal
import logging
from typing import Optional, Any
import urllib.parse

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.banks import get_bank_by_bin
from app.core.config import settings
from app.integrations.cloudinary import upload_order_receipt
from app.modules.favorites.models import Favorite
from app.modules.orders.models import (
    CancelledBy,
    FulfillmentMethod,
    Order,
    OrderItem,
    OrderStatus,
    OrderStatusHistory,
    PaymentMethod,
    PaymentStatus,
)
from app.modules.orders.repository import OrderRepository
from app.modules.orders.schemas import (
    CancelOrderRequest,
    ConfirmOrderRequest,
    CreateOrderRequest,
    OrderCursorPage,
    OrderDetailResponse,
    OrderItemResponse,
    OrderPaymentBankResponse,
    OrderStatusHistoryResponse,
    OrderSummaryResponse,
    UpdateOrderTransactionTermsRequest,
)
from app.modules.notifications.models import NotificationType
from app.modules.notifications.repository import NotificationRepository
from app.modules.notifications.schemas import NotificationResponse
from app.modules.orders.websocket import (
    publish_order_created,
    publish_order_updated,
    publish_user_event,
)
from app.modules.products.models import ListingType, Product, ProductStatus, ProductModerationStatus
from app.modules.users.capability_service import CapabilityService
from app.modules.users.models import User, UserStatus

logger = logging.getLogger("app.orders")


async def safe_publish_user_notification(user_id: int, notif_dto: NotificationResponse) -> None:
    """Best-effort post-commit realtime notification dispatch isolated per recipient."""
    try:
        await publish_user_event(
            user_id,
            {
                "type": "NOTIFICATION_CREATED",
                "notification": notif_dto.model_dump(mode="json"),
            },
        )
    except Exception as err:
        logger.warning(f"Failed to publish NOTIFICATION_CREATED to user {user_id}: {err}")


def normalize_to_utc_naive(dt: Optional[datetime]) -> Optional[datetime]:
    """Convert an offset-aware or offset-naive datetime to a UTC offset-naive datetime."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


class StockInvariantViolationError(HTTPException):
    def __init__(self, detail: str = "Lỗi dữ liệu tồn kho: số lượng giữ hàng không hợp lệ."):
        super().__init__(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=detail)


def generate_vietqr_url(
    bank_bin: str,
    account_number: str,
    amount: Decimal | int,
    order_code: str,
    account_name: str,
) -> str:
    """
    Generate a safe VietQR Quick Link URL via VietQR.io developer service.
    VietQR is a standard/brand of NAPAS.
    Inputs are safely URL-encoded to prevent malformed or injectable URLs.
    """
    safe_bin = urllib.parse.quote(str(bank_bin).strip(), safe="")
    safe_account = urllib.parse.quote(str(account_number).strip(), safe="")
    query_params = {
        "amount": str(int(amount)),
        "addInfo": order_code.strip(),
        "accountName": account_name.strip(),
    }
    encoded_query = urllib.parse.urlencode(query_params)
    return f"https://img.vietqr.io/image/{safe_bin}-{safe_account}-compact2.png?{encoded_query}"


def format_order_summary(order: Order) -> OrderSummaryResponse:
    primary_item = order.items[0] if order.items else None
    item_response = OrderItemResponse(
        order_item_id=primary_item.order_item_id if primary_item else 0,
        product_id=primary_item.product_id if primary_item else 0,
        product_title=primary_item.product_title if primary_item else "",
        product_image_url=primary_item.product_image_url if primary_item else None,
        quantity=primary_item.quantity if primary_item else 1,
        price_at_purchase=primary_item.price_at_purchase if primary_item else Decimal(0),
    )
    return OrderSummaryResponse(
        order_id=order.order_id,
        order_code=order.order_code,
        buyer_id=order.buyer_id,
        seller_id=order.seller_id,
        status=order.status,
        payment_method=order.payment_method,
        payment_status=order.payment_status.value if hasattr(order.payment_status, "value") else str(order.payment_status),
        fulfillment_method=order.fulfillment_method,
        total_amount=order.total_amount,
        item=item_response,
        created_at=order.created_at,
        updated_at=order.updated_at,
    )


def format_order_detail(order: Order) -> OrderDetailResponse:
    payment_bank: Optional[OrderPaymentBankResponse] = None

    # Expose bank snapshot and VietQR only for confirmed/active paid BANK_TRANSFER orders
    if (
        order.total_amount > Decimal(0)
        and order.payment_method == PaymentMethod.BANK_TRANSFER.value
        and order.status in (
            OrderStatus.CONFIRMED.value,
            OrderStatus.DELIVERING.value,
            OrderStatus.COMPLETED.value,
        )
        and order.payment_bank_bin
        and order.payment_bank_account_number
    ):
        bank_info = get_bank_by_bin(order.payment_bank_bin)
        account_name = order.payment_bank_account_name or ""
        qr_url = generate_vietqr_url(
            bank_bin=order.payment_bank_bin,
            account_number=order.payment_bank_account_number,
            amount=order.total_amount,
            order_code=order.order_code,
            account_name=account_name,
        )
        payment_bank = OrderPaymentBankResponse(
            bank_bin=order.payment_bank_bin,
            bank_code=bank_info.code if bank_info else order.payment_bank_bin,
            bank_name=bank_info.name if bank_info else "",
            bank_short_name=bank_info.short_name if bank_info else order.payment_bank_bin,
            account_number=order.payment_bank_account_number,
            account_name=account_name,
            qr_url=qr_url,
        )

    return OrderDetailResponse(
        order_id=order.order_id,
        order_code=order.order_code,
        buyer_id=order.buyer_id,
        buyer_name=order.buyer.full_name if order.buyer else f"User {order.buyer_id}",
        buyer_avatar_url=order.buyer.avatar_url if order.buyer else None,
        seller_id=order.seller_id,
        seller_name=order.seller.full_name if order.seller else f"User {order.seller_id}",
        seller_avatar_url=order.seller.avatar_url if order.seller else None,
        status=order.status,
        payment_method=order.payment_method,
        payment_status=order.payment_status.value if hasattr(order.payment_status, "value") else str(order.payment_status),
        payment_receipt_url=order.payment_receipt_url,
        receipt_uploaded_at=order.receipt_uploaded_at,
        paid_confirmed_at=order.paid_confirmed_at,
        payment_note=order.payment_note,
        payment_bank=payment_bank,
        fulfillment_method=order.fulfillment_method,
        meetup_place=order.meetup_place,
        meetup_time=order.meetup_time,
        shipping_address=order.shipping_address,
        shipping_expected_at=order.shipping_expected_at,
        contact_name=order.contact_name,
        contact_phone=order.contact_phone,
        buyer_note=order.buyer_note,
        total_amount=order.total_amount,
        auto_cancel_at=order.auto_cancel_at,
        confirmed_at=order.confirmed_at,
        completed_at=order.completed_at,
        cancelled_at=order.cancelled_at,
        cancelled_by=order.cancelled_by,
        cancel_reason=order.cancel_reason,
        items=[
            OrderItemResponse(
                order_item_id=item.order_item_id,
                product_id=item.product_id,
                product_title=item.product_title,
                product_image_url=item.product_image_url,
                quantity=item.quantity,
                price_at_purchase=item.price_at_purchase,
            )
            for item in order.items
        ],
        status_history=[
            OrderStatusHistoryResponse(
                history_id=h.history_id,
                from_status=h.from_status,
                to_status=h.to_status,
                changed_by=h.changed_by,
                note=h.note,
                created_at=h.created_at,
            )
            for h in order.status_history
        ],
        created_at=order.created_at,
        updated_at=order.updated_at,
    )


class OrderService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.order_repo = OrderRepository(db)

    async def create_direct_order(
        self, buyer: User, payload: CreateOrderRequest
    ) -> Order:
        if buyer.status != UserStatus.ACTIVE.value:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tài khoản của bạn không được phép đặt hàng.",
            )

        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

        if not await CapabilityService(self.db).can_user_buy(buyer.user_id, now_utc=now_utc):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "BUY_RESTRICTED",
                    "message": "Tài khoản của bạn đang bị giới hạn quyền mua hàng.",
                },
            )

        # 1. Lock product row exclusively
        stmt = (
            select(Product)
            .where(
                Product.product_id == payload.product_id,
                Product.is_deleted.is_(False),
            )
            .with_for_update()
        )
        result = await self.db.execute(stmt)
        product = result.scalar_one_or_none()

        if (
            not product
            or product.status != ProductStatus.AVAILABLE.value
            or product.moderation_status == ProductModerationStatus.BLOCKED.value
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Sản phẩm không tồn tại hoặc không khả dụng để đặt mua.",
            )

        seller = await self.db.get(User, product.seller_id)
        if not seller or seller.status != UserStatus.ACTIVE.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Người bán hiện đang bị khóa tài khoản hoặc không hoạt động.",
            )

        # Privacy-safe check: SELL-restricted seller returns 404
        if not await CapabilityService(self.db).can_user_sell(seller, now_utc=now_utc):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Sản phẩm không tồn tại hoặc không khả dụng để đặt mua.",
            )

        if product.seller_id == buyer.user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Không thể mua sản phẩm của chính mình.",
            )

        if product.listing_type != ListingType.FIXED_PRICE.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Sản phẩm đấu giá không thể mua trực tiếp qua chức năng này.",
            )

        # 2. Check stock availability
        available_qty = product.stock - product.reserved_stock
        if payload.quantity > available_qty:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Số lượng tồn kho khả dụng không đủ (còn {available_qty} sản phẩm).",
            )

        # 3. Reserve inventory
        product.reserved_stock += payload.quantity

        # 4. Resolve image snapshot
        image_url = None
        if product.images:
            for img in product.images:
                if img.is_thumbnail:
                    image_url = img.image_url
                    break
            if image_url is None and product.images:
                image_url = product.images[0].image_url

        price_at_purchase = product.price
        total_amount = price_at_purchase * payload.quantity

        # 5. Payment method & status derivation
        if total_amount == Decimal(0):
            # Free orders: internal sentinel OTHER, auto-paid, no seller confirmation required for payment
            payment_method = PaymentMethod.OTHER.value
            payment_status = PaymentStatus.PAID
            paid_confirmed_at = now_utc
        else:
            if payload.payment_method is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Vui lòng chọn phương thức thanh toán cho sản phẩm có phí.",
                )
            if payload.payment_method == PaymentMethod.OTHER:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Phương thức thanh toán không hợp lệ cho sản phẩm có phí.",
                )
            if payload.payment_method not in (PaymentMethod.CASH_ON_MEETUP, PaymentMethod.BANK_TRANSFER):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Phương thức thanh toán không hợp lệ.",
                )

            payment_method = payload.payment_method.value
            payment_status = PaymentStatus.UNPAID
            paid_confirmed_at = None

        auto_cancel_at = now_utc + timedelta(hours=settings.ORDER_CONFIRM_TIMEOUT_HOURS)

        order = Order(
            buyer_id=buyer.user_id,
            seller_id=product.seller_id,
            status=OrderStatus.PENDING.value,
            payment_method=payment_method,
            payment_status=payment_status,
            fulfillment_method=payload.fulfillment_method.value,
            meetup_place=payload.meetup_place.strip() if payload.meetup_place else None,
            meetup_time=normalize_to_utc_naive(payload.meetup_time),
            shipping_address=payload.shipping_address.strip() if payload.shipping_address else None,
            shipping_expected_at=normalize_to_utc_naive(payload.shipping_expected_at),
            contact_name=payload.contact_name.strip(),
            contact_phone=payload.contact_phone.strip(),
            buyer_note=payload.buyer_note.strip() if payload.buyer_note else None,
            total_amount=total_amount,
            auto_cancel_at=auto_cancel_at,
            paid_confirmed_at=paid_confirmed_at,
        )

        item = OrderItem(
            product_id=product.product_id,
            product_title=product.title,
            product_image_url=image_url,
            quantity=payload.quantity,
            price_at_purchase=price_at_purchase,
        )

        created_order = await self.order_repo.create_order(order, [item])

        await self.order_repo.add_status_history(
            order_id=created_order.order_id,
            from_status=None,
            to_status=OrderStatus.PENDING.value,
            changed_by=buyer.user_id,
            note="Đặt hàng thành công",
        )

        # Durable NEW_ORDER notification for seller within same transaction
        notification_repo = NotificationRepository(self.db)
        notification = await notification_repo.create(
            user_id=created_order.seller_id,
            type=NotificationType.NEW_ORDER.value,
            title="Bạn có đơn hàng mới",
            body=f"Đơn {created_order.order_code} vừa được tạo.",
            ref_type="ORDER",
            ref_id=created_order.order_id,
        )
        await self.db.flush()
        notification_snapshot = NotificationResponse.model_validate(notification)

        await self.db.commit()
        try:
            await publish_order_created(seller_id=created_order.seller_id, order_id=created_order.order_id)
            await publish_user_event(
                created_order.seller_id,
                {
                    "type": "NOTIFICATION_CREATED",
                    "notification": notification_snapshot.model_dump(mode="json"),
                },
            )
        except Exception as e:
            logger.error(f"Failed to publish order created / notification event: {e}")
        return await self.get_order_detail(created_order.order_id, buyer)

    async def create_auction_winner_order(
        self,
        winner: User,
        auction: Any,
        product: Product,
        payload: Any,
        now_utc: datetime,
    ) -> Order:
        # Note: reserved_stock is already 1 (held by auction close) and NOT incremented again!
        image_url = None
        if product.images:
            for img in product.images:
                if img.is_thumbnail:
                    image_url = img.image_url
                    break
            if image_url is None and product.images:
                image_url = product.images[0].image_url

        price_at_purchase = auction.final_price
        total_amount = price_at_purchase

        # Payment method validation
        if payload.payment_method not in (PaymentMethod.CASH_ON_MEETUP, PaymentMethod.BANK_TRANSFER):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Phương thức thanh toán không hợp lệ.",
            )

        payment_method = payload.payment_method.value
        payment_status = PaymentStatus.UNPAID
        paid_confirmed_at = None

        auto_cancel_at = now_utc + timedelta(hours=settings.ORDER_CONFIRM_TIMEOUT_HOURS)

        order = Order(
            buyer_id=winner.user_id,
            seller_id=product.seller_id,
            auction_id=auction.auction_id,
            status=OrderStatus.PENDING.value,
            payment_method=payment_method,
            payment_status=payment_status,
            fulfillment_method=payload.fulfillment_method.value,
            meetup_place=payload.meetup_place.strip() if payload.meetup_place else None,
            meetup_time=normalize_to_utc_naive(payload.meetup_time),
            shipping_address=payload.shipping_address.strip() if payload.shipping_address else None,
            contact_name=payload.contact_name.strip(),
            contact_phone=payload.contact_phone.strip(),
            buyer_note=payload.buyer_note.strip() if payload.buyer_note else None,
            total_amount=total_amount,
            auto_cancel_at=auto_cancel_at,
            paid_confirmed_at=paid_confirmed_at,
        )

        item = OrderItem(
            product_id=product.product_id,
            product_title=product.title,
            product_image_url=image_url,
            quantity=1,
            price_at_purchase=price_at_purchase,
        )

        created_order = await self.order_repo.create_order(order, [item])

        await self.order_repo.add_status_history(
            order_id=created_order.order_id,
            from_status=None,
            to_status=OrderStatus.PENDING.value,
            changed_by=winner.user_id,
            note="Đặt mua thành công từ kết quả trúng đấu giá",
        )

        # Durable NEW_ORDER notification for seller within caller transaction
        notification_repo = NotificationRepository(self.db)
        notification = await notification_repo.create(
            user_id=created_order.seller_id,
            type=NotificationType.NEW_ORDER.value,
            title="Bạn có đơn hàng mới",
            body=f"Đơn {created_order.order_code} vừa được tạo.",
            ref_type="ORDER",
            ref_id=created_order.order_id,
        )
        await self.db.flush()
        created_order._notification_snapshot = NotificationResponse.model_validate(notification)

        return created_order

    async def get_order_detail(self, order_id: int, current_user: User) -> Order:
        order = await self.order_repo.get_order_by_id(order_id)
        if not order or (
            order.buyer_id != current_user.user_id
            and order.seller_id != current_user.user_id
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Không tìm thấy đơn hàng.",
            )
        return order

    async def list_buying_orders(
        self,
        buyer: User,
        status_filter: Optional[str] = None,
        cursor: Optional[str] = None,
        limit: int = 20,
    ) -> OrderCursorPage:
        limit = max(1, min(limit, 50))
        cursor_data = self.order_repo.decode_cursor(cursor) if cursor else None
        orders = await self.order_repo.list_orders_by_buyer(
            buyer_id=buyer.user_id,
            status=status_filter,
            cursor_data=cursor_data,
            limit=limit,
        )

        has_more = len(orders) > limit
        if has_more:
            orders = orders[:limit]

        next_cursor = None
        if has_more and orders:
            last_order = orders[-1]
            next_cursor = self.order_repo.encode_cursor(
                last_order.created_at, last_order.order_id
            )

        return OrderCursorPage(
            items=[format_order_summary(o) for o in orders],
            next_cursor=next_cursor,
            has_more=has_more,
        )

    async def list_selling_orders(
        self,
        seller: User,
        status_filter: Optional[str] = None,
        cursor: Optional[str] = None,
        limit: int = 20,
    ) -> OrderCursorPage:
        limit = max(1, min(limit, 50))
        cursor_data = self.order_repo.decode_cursor(cursor) if cursor else None
        orders = await self.order_repo.list_orders_by_seller(
            seller_id=seller.user_id,
            status=status_filter,
            cursor_data=cursor_data,
            limit=limit,
        )

        has_more = len(orders) > limit
        if has_more:
            orders = orders[:limit]

        next_cursor = None
        if has_more and orders:
            last_order = orders[-1]
            next_cursor = self.order_repo.encode_cursor(
                last_order.created_at, last_order.order_id
            )

        return OrderCursorPage(
            items=[format_order_summary(o) for o in orders],
            next_cursor=next_cursor,
            has_more=has_more,
        )

    async def confirm_order(
        self, order_id: int, seller: User, payload: ConfirmOrderRequest
    ) -> Order:
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        order = await self.order_repo.get_order_by_id(order_id, for_update=True)
        if not order or order.seller_id != seller.user_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Không tìm thấy đơn hàng.",
            )

        if order.status != OrderStatus.PENDING.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Chỉ có thể xác nhận đơn hàng đang ở trạng thái chờ xác nhận.",
            )

        # Snapshot seller bank profile for paid BANK_TRANSFER orders
        if order.payment_method == PaymentMethod.BANK_TRANSFER.value and order.total_amount > Decimal(0):
            if not seller.bank_bin or not seller.bank_account_number or not seller.bank_account_name:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Bạn cần thiết lập tài khoản nhận tiền trước khi xác nhận đơn chuyển khoản.",
                )
            order.payment_bank_bin = seller.bank_bin
            order.payment_bank_account_number = seller.bank_account_number
            order.payment_bank_account_name = seller.bank_account_name

        order.status = OrderStatus.CONFIRMED.value
        order.confirmed_at = now_utc
        order.auto_cancel_at = None
        if payload.payment_note and payload.payment_note.strip():
            order.payment_note = payload.payment_note.strip()

        await self.order_repo.add_status_history(
            order_id=order.order_id,
            from_status=OrderStatus.PENDING.value,
            to_status=OrderStatus.CONFIRMED.value,
            changed_by=seller.user_id,
            note="Người bán đã xác nhận đơn hàng",
        )

        # Durable ORDER_STATUS notification for buyer within same transaction
        notification_repo = NotificationRepository(self.db)
        notif = await notification_repo.create(
            user_id=order.buyer_id,
            type=NotificationType.ORDER_STATUS.value,
            title="Đơn hàng đã được xác nhận",
            body=f"Đơn {order.order_code} đã được người bán xác nhận.",
            ref_type="ORDER",
            ref_id=order.order_id,
        )
        await self.db.flush()
        notification_snapshot = NotificationResponse.model_validate(notif)

        await self.db.commit()
        try:
            await publish_order_updated(buyer_id=order.buyer_id, seller_id=order.seller_id, order_id=order.order_id, reason="CONFIRMED")
        except Exception as e:
            logger.error(f"Failed to publish order confirmed event: {e}")
        await safe_publish_user_notification(order.buyer_id, notification_snapshot)
        return await self.get_order_detail(order.order_id, seller)

    async def upload_payment_receipt(
        self, order_id: int, buyer: User, file_bytes: bytes, content_type: str
    ) -> Order:
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        order = await self.order_repo.get_order_by_id(order_id, for_update=True)
        if not order or order.buyer_id != buyer.user_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Không tìm thấy đơn hàng.",
            )

        if order.total_amount == Decimal(0):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Đơn hàng miễn phí không yêu cầu biên nhận thanh toán.",
            )

        if order.status == OrderStatus.PENDING.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Đơn hàng phải được người bán xác nhận trước khi thanh toán chuyển khoản.",
            )

        if order.status != OrderStatus.CONFIRMED.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Chỉ có thể tải lên biên nhận thanh toán khi đơn hàng ở trạng thái đã xác nhận.",
            )

        if order.payment_status == PaymentStatus.PAID:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Không thể thay đổi biên nhận sau khi người bán đã xác nhận thanh toán.",
            )

        if order.payment_method != PaymentMethod.BANK_TRANSFER.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Chỉ áp dụng tải biên nhận cho phương thức chuyển khoản ngân hàng.",
            )

        # Validate image file
        allowed_mimes = {"image/jpeg", "image/png", "image/webp"}
        if content_type not in allowed_mimes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Định dạng ảnh không hợp lệ: '{content_type}'. Chỉ hỗ trợ JPEG, PNG, WEBP.",
            )

        if len(file_bytes) == 0 or len(file_bytes) > 5 * 1024 * 1024:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Kích thước ảnh biên nhận không được vượt quá 5MB và không được rỗng.",
            )

        # Upload to Cloudinary dedicated order folder
        upload_res = upload_order_receipt(file_bytes, order_id=order.order_id)
        order.payment_receipt_url = upload_res["secure_url"]
        order.receipt_uploaded_at = now_utc
        order.payment_status = PaymentStatus.VERIFYING

        await self.order_repo.add_status_history(
            order_id=order.order_id,
            from_status=order.status,
            to_status=order.status,
            changed_by=buyer.user_id,
            note="Người mua đã tải lên biên nhận thanh toán chuyển khoản",
        )

        # Durable ORDER_STATUS notification for seller within same transaction
        notification_repo = NotificationRepository(self.db)
        notif = await notification_repo.create(
            user_id=order.seller_id,
            type=NotificationType.ORDER_STATUS.value,
            title="Người mua đã gửi biên nhận",
            body=f"Đơn {order.order_code} đang chờ bạn kiểm tra thanh toán.",
            ref_type="ORDER",
            ref_id=order.order_id,
        )
        await self.db.flush()
        notification_snapshot = NotificationResponse.model_validate(notif)

        await self.db.commit()
        try:
            await publish_order_updated(buyer_id=order.buyer_id, seller_id=order.seller_id, order_id=order.order_id, reason="RECEIPT_UPLOADED")
        except Exception as e:
            logger.error(f"Failed to publish receipt uploaded event: {e}")
        await safe_publish_user_notification(order.seller_id, notification_snapshot)
        return await self.get_order_detail(order.order_id, buyer)

    async def confirm_payment(self, order_id: int, seller: User) -> Order:
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        order = await self.order_repo.get_order_by_id(order_id, for_update=True)
        if not order or order.seller_id != seller.user_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Không tìm thấy đơn hàng.",
            )

        if order.status not in (OrderStatus.CONFIRMED.value, OrderStatus.DELIVERING.value):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Đơn hàng phải ở trạng thái đã xác nhận hoặc đang giao để xác nhận thanh toán.",
            )

        if order.payment_status == PaymentStatus.PAID:
            return await self.get_order_detail(order.order_id, seller)  # Idempotent

        # Method-specific validations
        if order.payment_method == PaymentMethod.BANK_TRANSFER.value:
            if order.status != OrderStatus.CONFIRMED.value:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Đơn hàng chuyển khoản phải ở trạng thái đã xác nhận để xác nhận thanh toán.",
                )
            if order.payment_status != PaymentStatus.VERIFYING or not order.payment_receipt_url:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Không thể xác nhận thanh toán chuyển khoản khi người mua chưa tải lên biên nhận.",
                )
        elif order.payment_method == PaymentMethod.CASH_ON_MEETUP.value:
            if order.fulfillment_method == FulfillmentMethod.MEETUP.value and order.status != OrderStatus.CONFIRMED.value:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Đơn hàng gặp mặt trực tiếp phải ở trạng thái đã xác nhận để xác nhận thanh toán.",
                )
            if order.payment_status != PaymentStatus.UNPAID:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Không thể xác nhận thanh toán tiền mặt với trạng thái hiện tại.",
                )
        elif order.payment_method == PaymentMethod.OTHER.value:
            if order.total_amount > Decimal(0):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Không thể xác nhận thanh toán với trạng thái hiện tại.",
                )

        order.payment_status = PaymentStatus.PAID
        order.paid_confirmed_at = now_utc

        await self.order_repo.add_status_history(
            order_id=order.order_id,
            from_status=order.status,
            to_status=order.status,
            changed_by=seller.user_id,
            note="Người bán xác nhận đã nhận đủ thanh toán",
        )

        # Durable ORDER_STATUS notification for buyer within same transaction
        notification_repo = NotificationRepository(self.db)
        notif = await notification_repo.create(
            user_id=order.buyer_id,
            type=NotificationType.ORDER_STATUS.value,
            title="Thanh toán đã được xác nhận",
            body=f"Thanh toán cho đơn {order.order_code} đã được người bán xác nhận.",
            ref_type="ORDER",
            ref_id=order.order_id,
        )
        await self.db.flush()
        notification_snapshot = NotificationResponse.model_validate(notif)

        await self.db.commit()
        try:
            await publish_order_updated(buyer_id=order.buyer_id, seller_id=order.seller_id, order_id=order.order_id, reason="PAYMENT_CONFIRMED")
        except Exception as e:
            logger.error(f"Failed to publish payment confirmed event: {e}")
        await safe_publish_user_notification(order.buyer_id, notification_snapshot)
        return await self.get_order_detail(order.order_id, seller)

    async def mark_delivering(self, order_id: int, seller: User) -> Order:
        order = await self.order_repo.get_order_by_id(order_id, for_update=True)
        if not order or order.seller_id != seller.user_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Không tìm thấy đơn hàng.",
            )

        # Requirement 3: DELIVERING is SHIPPING-only
        if order.fulfillment_method != FulfillmentMethod.SHIPPING.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Hình thức gặp mặt trực tiếp (MEETUP) không sử dụng trạng thái đang giao hàng.",
            )

        if order.status != OrderStatus.CONFIRMED.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Chỉ có thể chuyển sang trạng thái đang giao từ trạng thái đã xác nhận.",
            )

        if (
            order.payment_method == PaymentMethod.BANK_TRANSFER.value
            and order.payment_status != PaymentStatus.PAID
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Đơn hàng chuyển khoản giao qua bưu điện/vận chuyển bắt buộc phải thanh toán trước khi giao.",
            )

        order.status = OrderStatus.DELIVERING.value

        await self.order_repo.add_status_history(
            order_id=order.order_id,
            from_status=OrderStatus.CONFIRMED.value,
            to_status=OrderStatus.DELIVERING.value,
            changed_by=seller.user_id,
            note="Người bán đã bắt đầu giao hàng",
        )

        # Durable ORDER_STATUS notification for buyer within same transaction
        notification_repo = NotificationRepository(self.db)
        notif = await notification_repo.create(
            user_id=order.buyer_id,
            type=NotificationType.ORDER_STATUS.value,
            title="Đơn hàng đang được giao",
            body=f"Đơn {order.order_code} đã bắt đầu được giao đến bạn.",
            ref_type="ORDER",
            ref_id=order.order_id,
        )
        await self.db.flush()
        notification_snapshot = NotificationResponse.model_validate(notif)

        await self.db.commit()
        try:
            await publish_order_updated(buyer_id=order.buyer_id, seller_id=order.seller_id, order_id=order.order_id, reason="DELIVERING")
        except Exception as e:
            logger.error(f"Failed to publish delivering event: {e}")
        await safe_publish_user_notification(order.buyer_id, notification_snapshot)
        return await self.get_order_detail(order.order_id, seller)

    async def update_transaction_terms(
        self,
        order_id: int,
        seller: User,
        payload: UpdateOrderTransactionTermsRequest,
    ) -> Order:
        order = await self.order_repo.get_order_by_id(order_id, for_update=True)
        if not order or order.seller_id != seller.user_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Không tìm thấy đơn hàng.",
            )

        if order.status not in (OrderStatus.PENDING.value, OrderStatus.CONFIRMED.value):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Chỉ có thể chỉnh sửa điều khoản giao dịch khi đơn hàng ở trạng thái chờ xác nhận hoặc đã xác nhận.",
            )

        # Snapshot canonical persisted terms before mutation
        before_terms = (
            order.payment_method,
            order.fulfillment_method,
            order.meetup_place,
            order.meetup_time,
            order.shipping_address,
            order.shipping_expected_at,
            order.payment_note,
        )

        # 1. Payment method updates
        if order.total_amount == Decimal(0):
            # Free orders: payment method remains internal sentinel OTHER
            pass
        else:
            if payload.payment_method is not None:
                if payload.payment_method == PaymentMethod.OTHER:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Phương thức thanh toán không hợp lệ cho đơn hàng có phí.",
                    )

                new_pay_method = payload.payment_method.value
                if new_pay_method != order.payment_method:
                    if order.payment_status in (PaymentStatus.VERIFYING, PaymentStatus.PAID):
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Không thể thay đổi phương thức thanh toán khi người mua đã chuyển khoản hoặc thanh toán đã hoàn tất.",
                        )

                    if new_pay_method == PaymentMethod.BANK_TRANSFER.value:
                        if not seller.bank_bin or not seller.bank_account_number or not seller.bank_account_name:
                            raise HTTPException(
                                status_code=status.HTTP_400_BAD_REQUEST,
                                detail="Bạn cần thiết lập tài khoản nhận tiền trước khi chuyển đơn sang hình thức chuyển khoản.",
                            )
                        # Snapshot seller bank if order is already CONFIRMED
                        if order.status == OrderStatus.CONFIRMED.value:
                            order.payment_bank_bin = seller.bank_bin
                            order.payment_bank_account_number = seller.bank_account_number
                            order.payment_bank_account_name = seller.bank_account_name
                    elif new_pay_method == PaymentMethod.CASH_ON_MEETUP.value:
                        # Clear bank snapshot
                        order.payment_bank_bin = None
                        order.payment_bank_account_number = None
                        order.payment_bank_account_name = None

                    order.payment_method = new_pay_method

        # 2. Fulfillment method & location updates
        new_fulfillment = (
            payload.fulfillment_method.value
            if payload.fulfillment_method is not None
            else order.fulfillment_method
        )

        if new_fulfillment == FulfillmentMethod.MEETUP.value:
            new_meetup_place = (
                payload.meetup_place.strip()
                if payload.meetup_place is not None
                else order.meetup_place
            )
            if not new_meetup_place:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Vui lòng nhập địa điểm hẹn gặp.",
                )
            order.fulfillment_method = FulfillmentMethod.MEETUP.value
            order.meetup_place = new_meetup_place
            if "meetup_time" in payload.model_fields_set or payload.meetup_time is not None:
                order.meetup_time = normalize_to_utc_naive(payload.meetup_time) if payload.meetup_time else None
            # Clear shipping fields
            order.shipping_address = None
            order.shipping_expected_at = None
        elif new_fulfillment == FulfillmentMethod.SHIPPING.value:
            new_shipping_address = (
                payload.shipping_address.strip()
                if payload.shipping_address is not None
                else order.shipping_address
            )
            if not new_shipping_address:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Vui lòng nhập địa chỉ giao hàng.",
                )
            order.fulfillment_method = FulfillmentMethod.SHIPPING.value
            order.shipping_address = new_shipping_address
            if "shipping_expected_at" in payload.model_fields_set or payload.shipping_expected_at is not None:
                order.shipping_expected_at = normalize_to_utc_naive(payload.shipping_expected_at) if payload.shipping_expected_at else None
            # Clear meetup fields
            order.meetup_place = None
            order.meetup_time = None

        # 3. Payment note update
        if payload.payment_note is not None:
            order.payment_note = payload.payment_note.strip() if payload.payment_note.strip() else None

        # Snapshot canonical persisted terms after mutation
        after_terms = (
            order.payment_method,
            order.fulfillment_method,
            order.meetup_place,
            order.meetup_time,
            order.shipping_address,
            order.shipping_expected_at,
            order.payment_note,
        )
        terms_changed = (before_terms != after_terms)

        notification_snapshot = None
        if terms_changed:
            notification_repo = NotificationRepository(self.db)
            notif = await notification_repo.create(
                user_id=order.buyer_id,
                type=NotificationType.ORDER_STATUS.value,
                title="Điều khoản đơn hàng đã được cập nhật",
                body=f"Người bán đã cập nhật thông tin giao dịch của đơn {order.order_code}.",
                ref_type="ORDER",
                ref_id=order.order_id,
            )
            await self.db.flush()
            notification_snapshot = NotificationResponse.model_validate(notif)

        await self.db.commit()
        try:
            await publish_order_updated(buyer_id=order.buyer_id, seller_id=order.seller_id, order_id=order.order_id, reason="TERMS_UPDATED")
        except Exception as e:
            logger.error(f"Failed to publish terms updated event: {e}")
        if notification_snapshot:
            await safe_publish_user_notification(order.buyer_id, notification_snapshot)
        return await self.get_order_detail(order.order_id, seller)

    async def complete_order(self, order_id: int, current_user: User) -> Order:
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        order = await self.order_repo.get_order_by_id(order_id, for_update=True)
        if not order or (
            order.buyer_id != current_user.user_id
            and order.seller_id != current_user.user_id
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Không tìm thấy đơn hàng.",
            )

        if order.status in (OrderStatus.COMPLETED.value, OrderStatus.CANCELLED.value):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Không thể hoàn tất đơn hàng đã kết thúc.",
            )

        # Allowed fulfillment flow states
        if order.fulfillment_method == FulfillmentMethod.MEETUP.value:
            if order.status != OrderStatus.CONFIRMED.value:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Đơn hàng gặp mặt trực tiếp phải ở trạng thái đã xác nhận để hoàn tất.",
                )
        elif order.fulfillment_method == FulfillmentMethod.SHIPPING.value:
            if order.status != OrderStatus.DELIVERING.value:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Đơn hàng vận chuyển phải ở trạng thái đang giao để hoàn tất.",
                )

        # Payment required before completion
        if order.payment_status != PaymentStatus.PAID:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Đơn hàng phải hoàn tất thanh toán trước khi xác nhận hoàn thành.",
            )

        # Finalize stock for each item in transaction
        for item in order.items:
            stmt = (
                select(Product)
                .where(Product.product_id == item.product_id)
                .with_for_update()
            )
            result = await self.db.execute(stmt)
            product = result.scalar_one_or_none()
            if not product:
                continue

            if product.reserved_stock < item.quantity or product.stock < item.quantity:
                logger.error(
                    f"INVARIANT VIOLATION on completion: product {product.product_id} "
                    f"stock={product.stock}, reserved_stock={product.reserved_stock}, item_qty={item.quantity}"
                )
                raise StockInvariantViolationError("Lỗi dữ liệu tồn kho: số lượng tồn kho không hợp lệ.")

            product.stock -= item.quantity
            product.reserved_stock -= item.quantity

            if product.stock == 0:
                product.status = ProductStatus.SOLD_OUT.value
                # Clean up favorites when real finalized stock reaches 0
                await self.db.execute(
                    delete(Favorite).where(Favorite.product_id == product.product_id)
                )

        old_status = order.status
        order.status = OrderStatus.COMPLETED.value
        order.completed_at = now_utc

        await self.order_repo.add_status_history(
            order_id=order.order_id,
            from_status=old_status,
            to_status=OrderStatus.COMPLETED.value,
            changed_by=current_user.user_id,
            note="Đơn hàng đã hoàn tất giao dịch",
        )

        # Durable ORDER_STATUS notification for non-actor within same transaction
        target_uid = order.seller_id if current_user.user_id == order.buyer_id else order.buyer_id
        notification_repo = NotificationRepository(self.db)
        notif = await notification_repo.create(
            user_id=target_uid,
            type=NotificationType.ORDER_STATUS.value,
            title="Đơn hàng đã hoàn tất",
            body=f"Đơn {order.order_code} đã được hoàn tất.",
            ref_type="ORDER",
            ref_id=order.order_id,
        )
        await self.db.flush()
        notification_snapshot = NotificationResponse.model_validate(notif)

        await self.db.commit()
        try:
            await publish_order_updated(buyer_id=order.buyer_id, seller_id=order.seller_id, order_id=order.order_id, reason="COMPLETED")
        except Exception as e:
            logger.error(f"Failed to publish completed event: {e}")
        await safe_publish_user_notification(target_uid, notification_snapshot)
        return await self.get_order_detail(order.order_id, current_user)

    async def cancel_order(
        self, order_id: int, current_user: User, payload: CancelOrderRequest
    ) -> Order:
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        order = await self.order_repo.get_order_by_id(order_id, for_update=True)
        if not order or (
            order.buyer_id != current_user.user_id
            and order.seller_id != current_user.user_id
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Không tìm thấy đơn hàng.",
            )

        if order.status == OrderStatus.CANCELLED.value:
            return await self.get_order_detail(order.order_id, current_user)  # Idempotent

        if order.status == OrderStatus.COMPLETED.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Không thể hủy đơn hàng đã hoàn tất.",
            )

        if order.status == OrderStatus.DELIVERING.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Không thể hủy đơn hàng đang trong quá trình giao hàng.",
            )

        if order.status == OrderStatus.CONFIRMED.value:
            # Free orders (total_amount == 0) can cancel in CONFIRMED
            if order.total_amount > Decimal(0) and order.payment_status != PaymentStatus.UNPAID:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Không thể hủy đơn hàng đã thanh toán hoặc đang xác thực biên nhận chuyển khoản.",
                )

        actor = CancelledBy.BUYER.value if current_user.user_id == order.buyer_id else CancelledBy.SELLER.value

        # Release stock for each item in transaction
        for item in order.items:
            stmt = (
                select(Product)
                .where(Product.product_id == item.product_id)
                .with_for_update()
            )
            result = await self.db.execute(stmt)
            product = result.scalar_one_or_none()
            if not product:
                continue

            if product.reserved_stock < item.quantity:
                logger.error(
                    f"INVARIANT VIOLATION on cancellation: product {product.product_id} "
                    f"reserved_stock={product.reserved_stock}, item_qty={item.quantity}"
                )
                raise StockInvariantViolationError("Lỗi dữ liệu tồn kho: số lượng giữ hàng không hợp lệ.")

            product.reserved_stock -= item.quantity

        old_status = order.status
        order.status = OrderStatus.CANCELLED.value
        order.cancelled_at = now_utc
        order.cancelled_by = actor
        order.cancel_reason = payload.cancel_reason.strip()

        await self.order_repo.add_status_history(
            order_id=order.order_id,
            from_status=old_status,
            to_status=OrderStatus.CANCELLED.value,
            changed_by=current_user.user_id,
            note=payload.cancel_reason.strip(),
        )

        # Durable ORDER_STATUS notification for non-actor within same transaction
        if current_user.user_id == order.buyer_id:
            target_uid = order.seller_id
            cancel_body = f"Người mua đã hủy đơn {order.order_code}."
        else:
            target_uid = order.buyer_id
            cancel_body = f"Người bán đã hủy đơn {order.order_code}."

        notification_repo = NotificationRepository(self.db)
        notif = await notification_repo.create(
            user_id=target_uid,
            type=NotificationType.ORDER_STATUS.value,
            title="Đơn hàng đã bị hủy",
            body=cancel_body,
            ref_type="ORDER",
            ref_id=order.order_id,
        )
        await self.db.flush()
        notification_snapshot = NotificationResponse.model_validate(notif)

        await self.db.commit()
        try:
            await publish_order_updated(buyer_id=order.buyer_id, seller_id=order.seller_id, order_id=order.order_id, reason="CANCELLED")
        except Exception as e:
            logger.error(f"Failed to publish cancelled event: {e}")
        await safe_publish_user_notification(target_uid, notification_snapshot)
        return await self.get_order_detail(order.order_id, current_user)

    async def auto_cancel_single_order(self, order_id: int) -> bool:
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        order = await self.order_repo.get_order_by_id(order_id, for_update=True)
        if (
            not order
            or order.status != OrderStatus.PENDING.value
            or not order.auto_cancel_at
            or order.auto_cancel_at > now_utc
        ):
            return False

        for item in order.items:
            stmt = (
                select(Product)
                .where(Product.product_id == item.product_id)
                .with_for_update()
            )
            result = await self.db.execute(stmt)
            product = result.scalar_one_or_none()
            if not product:
                continue

            if product.reserved_stock < item.quantity:
                logger.error(
                    f"INVARIANT VIOLATION on auto-cancel: product {product.product_id} "
                    f"reserved_stock={product.reserved_stock}, item_qty={item.quantity}"
                )
                raise StockInvariantViolationError("Lỗi dữ liệu tồn kho: số lượng giữ hàng không hợp lệ.")

            product.reserved_stock -= item.quantity

        order.status = OrderStatus.CANCELLED.value
        order.cancelled_at = now_utc
        order.cancelled_by = CancelledBy.SYSTEM.value
        order.cancel_reason = "Hết hạn xác nhận từ người bán (tự động hủy)"

        await self.order_repo.add_status_history(
            order_id=order.order_id,
            from_status=OrderStatus.PENDING.value,
            to_status=OrderStatus.CANCELLED.value,
            changed_by=None,
            note="System auto-cancel",
        )

        # Durable ORDER_STATUS notifications for BOTH buyer and seller within same transaction
        notification_repo = NotificationRepository(self.db)
        buyer_notif = await notification_repo.create(
            user_id=order.buyer_id,
            type=NotificationType.ORDER_STATUS.value,
            title="Đơn hàng đã tự động hủy",
            body=f"Đơn {order.order_code} đã tự động hủy do quá thời gian xác nhận.",
            ref_type="ORDER",
            ref_id=order.order_id,
        )
        seller_notif = await notification_repo.create(
            user_id=order.seller_id,
            type=NotificationType.ORDER_STATUS.value,
            title="Đơn hàng đã tự động hủy",
            body=f"Đơn {order.order_code} đã tự động hủy do quá thời gian xác nhận.",
            ref_type="ORDER",
            ref_id=order.order_id,
        )
        await self.db.flush()
        buyer_snapshot = NotificationResponse.model_validate(buyer_notif)
        seller_snapshot = NotificationResponse.model_validate(seller_notif)

        await self.db.commit()
        try:
            await publish_order_updated(buyer_id=order.buyer_id, seller_id=order.seller_id, order_id=order.order_id, reason="AUTO_CANCELLED")
        except Exception as e:
            logger.error(f"Failed to publish auto cancelled event: {e}")

        # Independent best-effort post-commit realtime dispatch
        await safe_publish_user_notification(order.buyer_id, buyer_snapshot)
        await safe_publish_user_notification(order.seller_id, seller_snapshot)
        return True
