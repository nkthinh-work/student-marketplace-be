from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import require_admin
from app.modules.feedback import service
from app.modules.feedback.schemas import (
    AdminSupportClaimCursorPage,
    AdminSupportClaimItem,
    AdminSupportClaimReject,
    AdminSupportClaimVerify,
)
from app.modules.users.models import User

router = APIRouter(prefix="/admin/support-claims", tags=["Admin Support Claims"])


@router.get(
    "",
    response_model=AdminSupportClaimCursorPage,
    status_code=status.HTTP_200_OK,
    summary="Hàng đợi đối soát các yêu cầu xác nhận ủng hộ dành cho quản trị viên",
)
async def list_support_claims(
    status_filter: Optional[str] = Query(None, alias="status", description="Lọc theo trạng thái (PENDING, VERIFIED, REJECTED)"),
    limit: int = Query(20, ge=1, le=50, description="Số lượng mục mỗi trang (1-50)"),
    cursor: Optional[str] = Query(None, description="Con trỏ phân trang Keyset"),
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminSupportClaimCursorPage:
    return await service.list_admin_support_claims(
        session=db,
        status_filter=status_filter,
        limit=limit,
        cursor=cursor,
    )


@router.post(
    "/{claim_id}/verify",
    response_model=AdminSupportClaimItem,
    status_code=status.HTTP_200_OK,
    summary="Quản trị viên xác thực khoản ủng hộ thực tế từ sao kê ngân hàng và tạo sổ cái",
)
async def verify_support_claim(
    claim_id: int,
    payload: AdminSupportClaimVerify,
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminSupportClaimItem:
    return await service.verify_admin_support_claim(
        session=db,
        claim_id=claim_id,
        current_admin=current_admin,
        payload=payload,
    )


@router.post(
    "/{claim_id}/reject",
    response_model=AdminSupportClaimItem,
    status_code=status.HTTP_200_OK,
    summary="Quản trị viên từ chối yêu cầu xác nhận khi không tìm thấy giao dịch ngân hàng khớp",
)
async def reject_support_claim(
    claim_id: int,
    payload: AdminSupportClaimReject,
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminSupportClaimItem:
    return await service.reject_admin_support_claim(
        session=db,
        claim_id=claim_id,
        current_admin=current_admin,
        payload=payload,
    )
