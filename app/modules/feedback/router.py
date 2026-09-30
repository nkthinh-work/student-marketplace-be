from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rate_limiter import rate_limit_write_mutation
from app.modules.auth.dependencies import get_current_active_user
from app.modules.feedback import service
from app.modules.feedback.schemas import (
    FeedbackCreateResponse,
    MyFeedbackCursorPage,
    PublicFeedbackCursorPage,
    SupportClaimCreate,
    SupportClaimUserItem,
    SupportClaimUserListPage,
    SupportResponse,
    SupporterLeaderboardResponse,
)
from app.modules.users.models import User

router = APIRouter(prefix="/feedback", tags=["Feedback"])


@router.post(
    "",
    response_model=FeedbackCreateResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit_write_mutation)],
    summary="Gửi phản hồi / góp ý về website kèm minh chứng hình ảnh/video",
)
async def submit_feedback(
    content: str = Form(..., description="Nội dung phản hồi từ 5 đến 500 ký tự"),
    images: List[UploadFile] = File(default=[], description="Tối đa 3 ảnh minh chứng (JPEG, PNG, WebP <= 10MB)"),
    video: Optional[UploadFile] = File(default=None, description="Tối đa 1 video minh chứng (MP4, WebM, MOV <= 30MB, <= 60 giây)"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> FeedbackCreateResponse:
    return await service.submit_feedback(
        session=db,
        current_user=current_user,
        content=content,
        images=images,
        video=video,
    )


@router.get(
    "",
    response_model=PublicFeedbackCursorPage,
    status_code=status.HTTP_200_OK,
    summary="Bảng tin phản hồi cộng đồng công khai (ẩn danh, chỉ gồm nội dung và thời gian)",
)
async def list_public_feedbacks(
    limit: int = Query(20, ge=1, le=50, description="Số lượng mục mỗi trang (1-50)"),
    cursor: Optional[str] = Query(None, description="Con trỏ phân trang"),
    db: AsyncSession = Depends(get_db),
) -> PublicFeedbackCursorPage:
    return await service.list_public_feedbacks(
        session=db,
        limit=limit,
        cursor=cursor,
    )


@router.get(
    "/me",
    response_model=MyFeedbackCursorPage,
    status_code=status.HTTP_200_OK,
    summary="Lấy danh sách phản hồi của chính người dùng hiện tại kèm minh chứng",
)
async def list_my_feedbacks(
    limit: int = Query(20, ge=1, le=50, description="Số lượng mục mỗi trang (1-50)"),
    cursor: Optional[str] = Query(None, description="Con trỏ phân trang"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> MyFeedbackCursorPage:
    return await service.list_my_feedbacks(
        session=db,
        current_user=current_user,
        limit=limit,
        cursor=cursor,
    )


@router.delete(
    "/{feedback_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Xóa phản hồi của chính mình (hard delete, xóa bản ghi DB và dọn dẹp media Cloudinary)",
)
async def delete_my_feedback(
    feedback_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await service.delete_user_feedback(
        session=db,
        feedback_id=feedback_id,
        current_user=current_user,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/support/leaderboard",
    response_model=SupporterLeaderboardResponse,
    status_code=status.HTTP_200_OK,
    summary="Bảng tri ân những người ủng hộ dự án công khai (Top 10)",
)
async def get_supporter_leaderboard(
    db: AsyncSession = Depends(get_db),
) -> SupporterLeaderboardResponse:
    return await service.get_supporter_leaderboard(db)


@router.get(
    "/support",
    response_model=SupportResponse,
    status_code=status.HTTP_200_OK,
    summary="Lấy thông tin người phát triển và mã VietQR ủng hộ dự án",
)
async def get_support_info(
    db: AsyncSession = Depends(get_db),
) -> SupportResponse:
    return await service.get_support_info(db)


@router.post(
    "/support/claims",
    response_model=SupportClaimUserItem,
    status_code=status.HTTP_201_CREATED,
    summary="Người dùng gửi xác nhận chuyển khoản ủng hộ dự án",
)
async def submit_support_claim(
    payload: SupportClaimCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> SupportClaimUserItem:
    return await service.create_user_support_claim(
        session=db,
        current_user=current_user,
        payload=payload,
    )


@router.get(
    "/support/claims/me",
    response_model=SupportClaimUserListPage,
    status_code=status.HTTP_200_OK,
    summary="Lấy danh sách các yêu cầu xác nhận ủng hộ của chính người dùng hiện tại",
)
async def list_my_support_claims(
    limit: int = Query(10, ge=1, le=50, description="Số lượng mục (1-50)"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> SupportClaimUserListPage:
    return await service.list_my_support_claims(
        session=db,
        current_user=current_user,
        limit=limit,
    )
