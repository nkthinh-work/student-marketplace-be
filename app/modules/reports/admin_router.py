from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import (
    authenticate_user_token,
    get_admin_for_evidence,
    get_current_active_user,
    get_current_user,
    get_token_payload,
    require_admin,
    security,
)
from app.modules.reports.models import (
    AdminReportQueueState,
    ReportConclusion,
    ReportStatus,
    ReportTargetType,
    ReportWorkflowState,
)
from app.modules.reports.schemas import (
    AdminEnforcementRequest,
    AdminReportDetailResponse,
    AdminReportListResponse,
    AdminReportResponse,
    AdminReportStatusUpdateRequest,
    SubjectReportHistoryResponse,
)
from app.modules.reports.service import ReportService
from app.modules.users.models import User, UserRole

router = APIRouter(prefix="/admin/reports", tags=["Admin Reports"])
admin_users_router = APIRouter(prefix="/admin/users", tags=["Admin Users"])



@router.get(
    "",
    response_model=AdminReportListResponse,
    status_code=status.HTTP_200_OK,
    summary="Danh sách hàng đợi báo cáo vi phạm dành cho quản trị viên",
)
async def list_admin_reports(
    queue_state: Optional[AdminReportQueueState] = Query(
        None, description="Lọc nhóm hàng đợi xử lý (NEEDS_ACTION, COMPLETED)"
    ),
    report_status: Optional[ReportStatus] = Query(
        None, alias="status", description="Lọc theo trạng thái báo cáo (cũ)"
    ),
    workflow: Optional[ReportWorkflowState] = Query(
        None, description="Lọc theo giai đoạn xử lý (OPEN, REVIEWING, COMPLETED)"
    ),
    conclusion: Optional[ReportConclusion] = Query(
        None, description="Lọc theo kết luận xử lý (SUPPORTED, INSUFFICIENT_EVIDENCE)"
    ),
    target_type: Optional[ReportTargetType] = Query(
        None, description="Lọc theo loại đối tượng (USER, PRODUCT, ORDER)"
    ),
    cursor: Optional[str] = Query(None, description="Con trỏ phân trang"),
    limit: int = Query(
        20, ge=1, le=50, description="Số lượng báo cáo trên một trang (1 - 50)"
    ),
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminReportListResponse:
    service = ReportService(db)
    return await service.list_admin_reports(
        current_admin=current_admin,
        limit=limit,
        cursor=cursor,
        queue_state=queue_state,
        report_status=report_status,
        workflow=workflow,
        conclusion=conclusion,
        target_type=target_type,
    )


@router.get(
    "/{report_id}",
    response_model=AdminReportDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Chi tiết báo cáo vi phạm dành cho quản trị viên",
)
async def get_admin_report_detail(
    report_id: int,
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminReportDetailResponse:
    service = ReportService(db)
    return await service.get_admin_report_detail(
        current_admin=current_admin,
        report_id=report_id,
    )


@router.patch(
    "/{report_id}/status",
    response_model=AdminReportDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Cập nhật trạng thái xử lý báo cáo vi phạm",
)
async def update_admin_report_status(
    report_id: int,
    payload: AdminReportStatusUpdateRequest,
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminReportDetailResponse:
    service = ReportService(db)
    return await service.update_admin_report_status(
        current_admin=current_admin,
        report_id=report_id,
        new_status=payload.status,
    )


@router.post(
    "/{report_id}/enforcement",
    response_model=AdminReportDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Thực hiện chế tài quản trị viên đối với đối tượng bị báo cáo (USER hoặc PRODUCT)",
)
async def enforce_admin_report_action(
    report_id: int,
    payload: AdminEnforcementRequest,
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminReportDetailResponse:
    service = ReportService(db)
    return await service.enforce_action(
        current_admin=current_admin,
        report_id=report_id,
        payload=payload,
    )


@router.get(
    "/{report_id}/evidence/{attachment_id}",
    summary="Truy xuất và tải luồng dữ liệu ảnh/video minh chứng báo cáo an toàn (Chỉ Admin)",
)
async def get_admin_report_evidence(
    request: Request,
    report_id: int,
    attachment_id: int,
    variant: Literal["thumbnail", "full"] = Query(
        "thumbnail", description="Biến thể kích thước ảnh: thumbnail hoặc full"
    ),
    current_admin: User = Depends(get_admin_for_evidence),
    db: AsyncSession = Depends(get_db),
):
    service = ReportService(db)
    range_header = request.headers.get("range")
    return await service.stream_admin_evidence(
        current_admin=current_admin,
        report_id=report_id,
        attachment_id=attachment_id,
        variant=variant,
        range_header=range_header,
    )


@admin_users_router.get(
    "/{user_id}/report-history",
    response_model=SubjectReportHistoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Lịch sử các báo cáo vi phạm liên quan đến người dùng",
)
async def get_user_report_history(
    user_id: int,
    limit: int = Query(5, ge=1, le=20, description="Số lượng mục trên một trang (1 - 20)"),
    cursor: Optional[str] = Query(None, description="Con trỏ phân trang"),
    exclude_report_id: Optional[int] = Query(None, description="ID báo cáo cần loại trừ khỏi lịch sử"),
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> SubjectReportHistoryResponse:
    service = ReportService(db)
    return await service.get_subject_report_history(
        current_admin=current_admin,
        subject_user_id=user_id,
        limit=limit,
        cursor=cursor,
        exclude_report_id=exclude_report_id,
    )

