from typing import Optional
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_active_user
from app.modules.orders.models import OrderStatus
from app.modules.orders.schemas import (
    CancelOrderRequest,
    ConfirmOrderRequest,
    CreateOrderRequest,
    OrderCursorPage,
    OrderDetailResponse,
    UpdateOrderTransactionTermsRequest,
)
from app.modules.orders.service import OrderService, format_order_detail
from app.modules.users.models import User

router = APIRouter(prefix="/orders", tags=["Orders"])


@router.post(
    "",
    response_model=OrderDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Tạo đơn hàng mua trực tiếp từ tin đăng",
)
async def create_order(
    payload: CreateOrderRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> OrderDetailResponse:
    service = OrderService(db)
    order = await service.create_direct_order(current_user, payload)
    return format_order_detail(order)


@router.get(
    "/me/buying",
    response_model=OrderCursorPage,
    summary="Lấy danh sách đơn mua của người dùng hiện tại (Cursor Pagination)",
)
async def list_buying_orders(
    status: Optional[str] = Query(None, description="Lọc theo OrderStatus (PENDING, CONFIRMED, DELIVERING, COMPLETED, CANCELLED)"),
    cursor: Optional[str] = Query(None, description="Cursor cho phân trang keyset"),
    limit: int = Query(20, ge=1, le=50, description="Số lượng đơn hàng tối đa mỗi trang"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> OrderCursorPage:
    service = OrderService(db)
    return await service.list_buying_orders(
        buyer=current_user,
        status_filter=status,
        cursor=cursor,
        limit=limit,
    )


@router.get(
    "/me/selling",
    response_model=OrderCursorPage,
    summary="Lấy danh sách đơn bán của người dùng hiện tại (Cursor Pagination)",
)
async def list_selling_orders(
    status: Optional[str] = Query(None, description="Lọc theo OrderStatus"),
    cursor: Optional[str] = Query(None, description="Cursor cho phân trang keyset"),
    limit: int = Query(20, ge=1, le=50, description="Số lượng đơn hàng tối đa mỗi trang"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> OrderCursorPage:
    service = OrderService(db)
    return await service.list_selling_orders(
        seller=current_user,
        status_filter=status,
        cursor=cursor,
        limit=limit,
    )


@router.get(
    "/{order_id}",
    response_model=OrderDetailResponse,
    summary="Xem chi tiết đơn hàng (Chỉ người mua và người bán của đơn)",
)
async def get_order_detail(
    order_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> OrderDetailResponse:
    service = OrderService(db)
    order = await service.get_order_detail(order_id, current_user)
    return format_order_detail(order)


@router.post(
    "/{order_id}/confirm",
    response_model=OrderDetailResponse,
    summary="Người bán xác nhận đơn hàng",
)
async def confirm_order(
    order_id: int,
    payload: ConfirmOrderRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> OrderDetailResponse:
    service = OrderService(db)
    order = await service.confirm_order(order_id, current_user, payload)
    return format_order_detail(order)


@router.patch(
    "/{order_id}/transaction-terms",
    response_model=OrderDetailResponse,
    summary="Người bán chỉnh sửa điều khoản giao nhận & thanh toán của đơn hàng",
)
async def update_transaction_terms(
    order_id: int,
    payload: UpdateOrderTransactionTermsRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> OrderDetailResponse:
    service = OrderService(db)
    order = await service.update_transaction_terms(order_id, current_user, payload)
    return format_order_detail(order)


@router.post(
    "/{order_id}/receipt",
    response_model=OrderDetailResponse,
    summary="Người mua tải lên biên nhận thanh toán chuyển khoản",
)
async def upload_payment_receipt(
    order_id: int,
    file: UploadFile = File(..., description="File ảnh biên nhận (JPEG, PNG, WEBP, tối đa 5MB)"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> OrderDetailResponse:
    service = OrderService(db)
    content_type = file.content_type or "image/jpeg"
    file_bytes = await file.read()
    order = await service.upload_payment_receipt(
        order_id=order_id,
        buyer=current_user,
        file_bytes=file_bytes,
        content_type=content_type,
    )
    return format_order_detail(order)


@router.post(
    "/{order_id}/confirm-payment",
    response_model=OrderDetailResponse,
    summary="Người bán xác nhận đã nhận đủ thanh toán",
)
async def confirm_payment(
    order_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> OrderDetailResponse:
    service = OrderService(db)
    order = await service.confirm_payment(order_id, current_user)
    return format_order_detail(order)


@router.post(
    "/{order_id}/deliver",
    response_model=OrderDetailResponse,
    summary="Người bán bắt đầu giao hàng (Chỉ dành cho hình thức SHIPPING)",
)
async def mark_delivering(
    order_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> OrderDetailResponse:
    service = OrderService(db)
    order = await service.mark_delivering(order_id, current_user)
    return format_order_detail(order)


@router.post(
    "/{order_id}/complete",
    response_model=OrderDetailResponse,
    summary="Hoàn tất đơn hàng và chốt tồn kho thực tế",
)
async def complete_order(
    order_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> OrderDetailResponse:
    service = OrderService(db)
    order = await service.complete_order(order_id, current_user)
    return format_order_detail(order)


@router.post(
    "/{order_id}/cancel",
    response_model=OrderDetailResponse,
    summary="Hủy đơn hàng và giải phóng số lượng giữ hàng",
)
async def cancel_order(
    order_id: int,
    payload: CancelOrderRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> OrderDetailResponse:
    service = OrderService(db)
    order = await service.cancel_order(order_id, current_user, payload)
    return format_order_detail(order)
