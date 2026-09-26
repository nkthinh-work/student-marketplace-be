from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import require_admin
from app.modules.feedback import service
from app.modules.feedback.schemas import (
    AdminSupportContributionCreate,
    AdminSupportContributionCursorPage,
    AdminSupportContributionItem,
    AdminSupportContributionVisibilityUpdate,
    SupporterResolveResponse,
)
from app.modules.users.models import User

router = APIRouter(prefix="/admin/support-contributions", tags=["Admin Support Contributions"])


@router.get(
    "/search-supporters",
    response_model=List[SupporterResolveResponse],
    status_code=status.HTTP_200_OK,
    summary="Quản trị viên tìm kiếm người ủng hộ theo tên hoặc User ID cho luồng ghi nhận thủ công",
)
async def search_supporters(
    query: str = Query(..., min_length=1, max_length=50, description="Tên người dùng hoặc User ID"),
    limit: int = Query(10, ge=1, le=20, description="Số lượng kết quả tối đa (1-20)"),
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> List[SupporterResolveResponse]:
    return await service.search_supporters_for_admin(session=db, query=query, limit=limit)


@router.post(
    "",
    response_model=AdminSupportContributionItem,
    status_code=status.HTTP_201_CREATED,
    summary="Quản trị viên ghi nhận khoản ủng hộ thực tế đã xác minh",
)
async def create_support_contribution(
    payload: AdminSupportContributionCreate,
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminSupportContributionItem:
    return await service.create_admin_support_contribution(
        session=db,
        current_admin=current_admin,
        payload=payload,
    )


@router.get(
    "",
    response_model=AdminSupportContributionCursorPage,
    status_code=status.HTTP_200_OK,
    summary="Sổ cái các khoản ủng hộ dành cho quản trị viên",
)
async def list_support_contributions(
    limit: int = Query(20, ge=1, le=50, description="Số lượng mục mỗi trang (1-50)"),
    cursor: Optional[str] = Query(None, description="Con trỏ phân trang"),
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminSupportContributionCursorPage:
    return await service.list_admin_support_contributions(
        session=db,
        limit=limit,
        cursor=cursor,
    )


@router.patch(
    "/{contribution_id}/visibility",
    response_model=AdminSupportContributionItem,
    status_code=status.HTTP_200_OK,
    summary="Quản trị viên chuyển đổi trạng thái hiển thị công khai trên Bảng tri ân",
)
async def update_support_contribution_visibility(
    contribution_id: int,
    payload: AdminSupportContributionVisibilityUpdate,
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminSupportContributionItem:
    return await service.update_support_contribution_visibility(
        session=db,
        contribution_id=contribution_id,
        is_public=payload.is_public,
    )


@router.delete(
    "/{contribution_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Quản trị viên xóa bản ghi đóng góp sai sót / nhầm lẫn",
)
async def delete_support_contribution(
    contribution_id: int,
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await service.delete_admin_support_contribution(
        session=db,
        contribution_id=contribution_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
