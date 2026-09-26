from typing import Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import require_admin
from app.modules.users.models import User
from app.modules.products.schemas import (
    AdminProductApprovalListResponse,
    AdminProductApprovalDetailResponse,
    AdminApprovalDecisionRequest,
)
from app.modules.products.service import ProductService

router = APIRouter(prefix="/admin/product-approvals", tags=["Admin Product Approvals"])


@router.get(
    "",
    response_model=AdminProductApprovalListResponse,
    status_code=status.HTTP_200_OK,
    summary="Danh sách tin đăng chờ duyệt dành cho quản trị viên",
)
async def list_admin_product_approvals(
    state: str = Query("PENDING", description="Lọc theo trạng thái duyệt (PENDING, APPROVED, REJECTED)"),
    limit: int = Query(20, ge=1, le=50, description="Số lượng bản ghi mỗi trang"),
    cursor: Optional[str] = Query(None, description="Cursor phân trang keyset"),
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    service = ProductService(db)
    return await service.list_admin_approvals(
        approval_status=state.upper(),
        limit=limit,
        cursor=cursor,
    )


@router.get(
    "/{product_id}",
    response_model=AdminProductApprovalDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Chi tiết tin đăng kiểm duyệt",
)
async def get_admin_product_approval_detail(
    product_id: int,
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    service = ProductService(db)
    return await service.get_admin_approval_detail(product_id)


@router.post(
    "/{product_id}/decision",
    response_model=AdminProductApprovalDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Quyết định duyệt hoặc từ chối tin đăng",
)
async def admin_product_approval_decision(
    product_id: int,
    data: AdminApprovalDecisionRequest,
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    service = ProductService(db)
    return await service.admin_decision(product_id, current_admin, data)
