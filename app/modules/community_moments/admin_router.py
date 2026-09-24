from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import require_admin
from app.modules.community_moments.schemas import (
    AdminCommunityMomentCursorPage,
    AdminCommunityMomentItem,
    CommunityMomentActionResponse,
)
from app.modules.community_moments.service import CommunityMomentService
from app.modules.users.models import User

router = APIRouter(prefix="/admin/community-moments", tags=["Admin Community Moments"])


@router.get(
    "",
    response_model=AdminCommunityMomentCursorPage,
    status_code=status.HTTP_200_OK,
    summary="Hàng đợi kiểm duyệt ảnh cộng đồng dành cho quản trị viên",
)
async def list_admin_community_moments(
    status_filter: Optional[str] = Query(
        "PENDING",
        alias="status",
        description="Lọc theo trạng thái kiểm duyệt (PENDING, APPROVED). Mặc định: PENDING",
    ),
    cursor: Optional[str] = Query(None, description="Con trỏ phân trang"),
    limit: int = Query(20, ge=1, le=50, description="Số lượng mục mỗi trang (1-50)"),
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminCommunityMomentCursorPage:
    service = CommunityMomentService(db)
    return await service.list_admin_moments(
        status=status_filter,
        cursor=cursor,
        limit=limit,
    )


@router.get(
    "/{moment_id}",
    response_model=AdminCommunityMomentItem,
    status_code=status.HTTP_200_OK,
    summary="Chi tiết ảnh cộng đồng dành cho quản trị viên",
)
async def get_admin_community_moment_detail(
    moment_id: int,
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminCommunityMomentItem:
    service = CommunityMomentService(db)
    return await service.get_admin_moment_detail(moment_id=moment_id)


@router.post(
    "/{moment_id}/approve",
    response_model=AdminCommunityMomentItem,
    status_code=status.HTTP_200_OK,
    summary="Phê duyệt ảnh cộng đồng (tự động xuất hiện trên Hero nếu trong top 5 mới nhất)",
)
async def approve_community_moment(
    moment_id: int,
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminCommunityMomentItem:
    service = CommunityMomentService(db)
    return await service.approve_moment(
        current_admin=current_admin,
        moment_id=moment_id,
    )


@router.post(
    "/{moment_id}/reject",
    response_model=CommunityMomentActionResponse,
    status_code=status.HTTP_200_OK,
    summary="Từ chối ảnh cộng đồng (xóa vĩnh viễn khỏi hệ thống và lưu trữ)",
)
async def reject_community_moment(
    moment_id: int,
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> CommunityMomentActionResponse:
    service = CommunityMomentService(db)
    return await service.reject_moment(
        current_admin=current_admin,
        moment_id=moment_id,
    )


@router.delete(
    "/{moment_id}",
    response_model=CommunityMomentActionResponse,
    status_code=status.HTTP_200_OK,
    summary="Xóa ảnh cộng đồng khỏi Hero (xóa vĩnh viễn khỏi hệ thống và lưu trữ)",
)
async def delete_community_moment(
    moment_id: int,
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> CommunityMomentActionResponse:
    service = CommunityMomentService(db)
    return await service.delete_admin_moment(
        current_admin=current_admin,
        moment_id=moment_id,
    )
