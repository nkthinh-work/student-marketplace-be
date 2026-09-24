from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import require_admin, get_admin_for_evidence
from app.modules.feedback import service
from app.modules.feedback.schemas import (
    AdminFeedbackDetail,
    AdminFeedbackListPage,
)
from app.modules.users.models import User

router = APIRouter(prefix="/admin/feedback", tags=["Admin Feedback"])


@router.get(
    "",
    response_model=AdminFeedbackListPage,
    status_code=status.HTTP_200_OK,
    summary="Danh sách phản hồi người dùng dành cho quản trị viên",
)
async def list_admin_feedbacks(
    cursor: Optional[str] = Query(None, description="Con trỏ phân trang"),
    limit: int = Query(20, ge=1, le=50, description="Số lượng mục mỗi trang (1-50)"),
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminFeedbackListPage:
    return await service.list_admin_feedbacks(
        session=db,
        limit=limit,
        cursor=cursor,
    )


@router.get(
    "/{feedback_id}",
    response_model=AdminFeedbackDetail,
    status_code=status.HTTP_200_OK,
    summary="Chi tiết phản hồi người dùng kèm danh sách minh chứng",
)
async def get_admin_feedback_detail(
    feedback_id: int,
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminFeedbackDetail:
    return await service.get_admin_feedback_detail(
        session=db,
        feedback_id=feedback_id,
    )


@router.delete(
    "/{feedback_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Quản trị viên xóa phản hồi (hard delete)",
)
async def delete_admin_feedback(
    feedback_id: int,
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await service.delete_admin_feedback(
        session=db,
        feedback_id=feedback_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{feedback_id}/evidence/{attachment_id}",
    summary="Tải hoặc phát trực tiếp minh chứng phản hồi an toàn (hỗ trợ HTTP Range 206)",
)
async def stream_feedback_evidence(
    feedback_id: int,
    attachment_id: int,
    range_header: Optional[str] = Header(None, alias="Range"),
    current_admin: User = Depends(get_admin_for_evidence),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    return await service.stream_feedback_evidence(
        session=db,
        feedback_id=feedback_id,
        attachment_id=attachment_id,
        range_header=range_header,
    )

