from typing import Sequence
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.tutorials.schemas import PublicTutorialResponse
from app.modules.tutorials.service import TutorialService

router = APIRouter(prefix="/tutorials", tags=["Tutorials"])


@router.get(
    "",
    response_model=list[PublicTutorialResponse],
    status_code=status.HTTP_200_OK,
    summary="Danh sách video hướng dẫn đã xuất bản cho người dùng",
)
async def list_public_tutorials(
    db: AsyncSession = Depends(get_db),
) -> Sequence[PublicTutorialResponse]:
    """Lấy danh sách các tutorial đang ở trạng thái đã xuất bản (is_published = true)."""
    service = TutorialService(db)
    return await service.get_public_tutorials()
