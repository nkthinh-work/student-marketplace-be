from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_active_user
from app.modules.community_moments.schemas import (
    CommunityMomentSubmissionResponse,
    PublicHeroResponse,
)
from app.modules.community_moments.service import CommunityMomentService
from app.modules.users.models import User

router = APIRouter(prefix="/community-moments", tags=["Community Moments"])


@router.post(
    "",
    response_model=CommunityMomentSubmissionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Đăng ảnh khoảnh khắc cộng đồng (chờ quản trị viên duyệt)",
)
async def submit_community_moment(
    file: UploadFile = File(..., description="Tệp ảnh khoảnh khắc (JPEG, PNG, WebP, max 10MB)"),
    note: str = Form(..., description="Lời nhắn khoảnh khắc (1..80 ký tự, một dòng)"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> CommunityMomentSubmissionResponse:
    service = CommunityMomentService(db)
    return await service.submit_moment(uploader=current_user, file=file, note=note)


@router.get(
    "/hero",
    response_model=PublicHeroResponse,
    status_code=status.HTTP_200_OK,
    summary="Lấy danh sách tối đa 5 ảnh khoảnh khắc đã duyệt cho Hero trang chủ",
)
async def get_public_hero_moments(
    db: AsyncSession = Depends(get_db),
) -> PublicHeroResponse:
    service = CommunityMomentService(db)
    return await service.get_public_hero_moments()
