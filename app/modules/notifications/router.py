from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_active_user
from app.modules.notifications.schemas import (
    NotificationListResponse,
    UnreadCountResponse,
)
from app.modules.notifications.service import NotificationService
from app.modules.users.models import User

router = APIRouter(prefix="/notifications", tags=["Notifications"])


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


# Static route MUST be registered BEFORE parameterized /{notification_id}/read
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
