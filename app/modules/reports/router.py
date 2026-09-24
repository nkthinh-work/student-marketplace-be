from fastapi import APIRouter, Depends, File, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_active_user
from app.modules.reports.schemas import (
    ReportCreateRequest,
    ReportEvidenceUploadResponse,
    ReportResponse,
)
from app.modules.reports.service import ReportService
from app.modules.users.models import User

router = APIRouter(prefix="/reports", tags=["Reports"])


@router.post(
    "",
    response_model=ReportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Tạo báo cáo vi phạm mới (User, Product, Order)",
)
async def create_report(
    payload: ReportCreateRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> ReportResponse:
    service = ReportService(db)
    report = await service.create_report(current_user, payload)
    return ReportResponse.model_validate(report)


@router.post(
    "/{report_id}/evidence",
    response_model=ReportEvidenceUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Tải lên ảnh minh chứng cho báo cáo vi phạm",
)
async def upload_report_evidence(
    report_id: int,
    files: list[UploadFile] = File(...),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> ReportEvidenceUploadResponse:
    service = ReportService(db)
    return await service.upload_evidence(current_user, report_id, files)
