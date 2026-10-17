from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_active_user
from app.modules.notifications.schemas import (
    NotificationListResponse,
    UnreadCountResponse,
    PushSubscribeRequest,
    PushUnsubscribeRequest,
    PushSubscriptionResponse,
)
from app.modules.notifications.service import NotificationService
from app.modules.users.models import User

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.post(
    "/push/subscribe",
    response_model=PushSubscriptionResponse,
    status_code=status.HTTP_200_OK,
    summary="Đăng ký hoặc cập nhật FCM Web Push token của thiết bị",
)
async def subscribe_push_token(
    payload: PushSubscribeRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> PushSubscriptionResponse:
    if not payload.fcm_token.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="FCM token không được để trống.",
        )
    service = NotificationService(db)
    await service.subscribe_push_token(
        user_id=current_user.user_id,
        fcm_token=payload.fcm_token.strip(),
        device_info=payload.device_info,
    )
    return PushSubscriptionResponse(status="subscribed")


@router.post(
    "/push/unsubscribe",
    response_model=PushSubscriptionResponse,
    status_code=status.HTTP_200_OK,
    summary="Hủy đăng ký FCM Web Push token của thiết bị",
)
async def unsubscribe_push_token(
    payload: PushUnsubscribeRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> PushSubscriptionResponse:
    service = NotificationService(db)
    await service.unsubscribe_push_token(
        user_id=current_user.user_id,
        fcm_token=payload.fcm_token.strip(),
    )
    return PushSubscriptionResponse(status="unsubscribed")


@router.get(
    "",
    response_model=NotificationListResponse,
    summary="Lấy danh sách thông báo của người dùng hiện tại (Cursor Pagination)",
)
async def list_notifications(
    limit: int = Query(20, ge=1, le=50, description="Số lượng thông báo tối đa mỗi trang"),
    cursor: Optional[str] = Query(None, description="Cursor cho phân trang keyset"),
    unread_only: bool = Query(False, description="Chỉ hiển thị thông báo chưa đọc"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationListResponse:
    service = NotificationService(db)
    return await service.list_notifications(
        user_id=current_user.user_id,
        limit=limit,
        cursor=cursor,
        unread_only=unread_only,
    )


@router.get(
    "/unread-count",
    response_model=UnreadCountResponse,
    summary="Lấy số lượng thông báo chưa đọc",
)
async def get_unread_count(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> UnreadCountResponse:
    service = NotificationService(db)
    return await service.get_unread_count(current_user.user_id)


# Route tĩnh phải đăng ký trước route có tham số /{notification_id}/read để tránh nuốt route
@router.patch(
    "/read-all",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Đánh dấu tất cả thông báo đã đọc",
)
async def mark_all_read(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    service = NotificationService(db)
    await service.mark_all_read(current_user.user_id)
    return None


@router.patch(
    "/{notification_id}/read",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Đánh dấu một thông báo đã đọc",
)
async def mark_read(
    notification_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    service = NotificationService(db)
    found = await service.mark_read(notification_id, current_user.user_id)
    if not found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy thông báo.",
        )
    return None


@router.delete(
    "/{notification_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Xóa một thông báo của người dùng",
)
async def delete_notification(
    notification_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    service = NotificationService(db)
    found = await service.delete_notification(notification_id, current_user.user_id)
    if not found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy thông báo.",
        )
    return None
