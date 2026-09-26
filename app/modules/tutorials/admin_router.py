from typing import Optional, Sequence
from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import require_admin
from app.modules.tutorials.schemas import (
    AdminTutorialReorderRequest,
    AdminTutorialResponse,
    AdminTutorialUpdate,
)
from app.modules.tutorials.service import TutorialService
from app.modules.users.models import User

router = APIRouter(prefix="/admin/tutorials", tags=["Admin Tutorials"])


@router.get(
    "",
    response_model=list[AdminTutorialResponse],
    status_code=status.HTTP_200_OK,
    summary="Danh sách tất cả tutorial (kể cả bản nháp) dành cho quản trị viên",
)
async def list_admin_tutorials(
    feature_key: Optional[str] = Query(None, description="Lọc theo nhóm tính năng"),
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Sequence[AdminTutorialResponse]:
    service = TutorialService(db)
    return await service.get_admin_tutorials(feature_key=feature_key)


@router.get(
    "/{tutorial_id}",
    response_model=AdminTutorialResponse,
    status_code=status.HTTP_200_OK,
    summary="Chi tiết một tutorial dành cho quản trị viên",
)
async def get_admin_tutorial_detail(
    tutorial_id: int,
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminTutorialResponse:
    service = TutorialService(db)
    return await service.get_admin_tutorial_detail(tutorial_id=tutorial_id)


@router.post(
    "",
    response_model=AdminTutorialResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Tạo mới video tutorial với video MP4 9:16",
)
async def create_tutorial(
    video: UploadFile = File(..., description="Tệp video MP4 dọc 9:16"),
    feature_key: str = Form(..., description="Mã nhóm tính năng hợp lệ"),
    title: str = Form(..., description="Tiêu đề tutorial (tối đa 120 ký tự)"),
    description: Optional[str] = Form(None, description="Mô tả ngắn (tối đa 500 ký tự)"),
    action_key: Optional[str] = Form(None, description="Mã hành động sau khi xem"),
    is_published: bool = Form(False, description="Trạng thái xuất bản"),
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminTutorialResponse:
    service = TutorialService(db)
    return await service.create_tutorial(
        current_admin_id=current_admin.user_id,
        feature_key=feature_key,
        title=title,
        description=description,
        action_key=action_key,
        is_published=is_published,
        video_file=video,
    )


@router.patch(
    "/reorder",
    response_model=list[AdminTutorialResponse],
    status_code=status.HTTP_200_OK,
    summary="Sắp xếp lại thứ tự các tutorial trong cùng một nhóm tính năng",
)
async def reorder_tutorials(
    payload: AdminTutorialReorderRequest,
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Sequence[AdminTutorialResponse]:
    service = TutorialService(db)
    return await service.reorder_tutorials(payload=payload)


@router.patch(
    "/{tutorial_id}",
    response_model=AdminTutorialResponse,
    status_code=status.HTTP_200_OK,
    summary="Cập nhật metadata của tutorial",
)
async def update_tutorial_metadata(
    tutorial_id: int,
    payload: AdminTutorialUpdate,
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminTutorialResponse:
    service = TutorialService(db)
    return await service.update_tutorial_metadata(
        tutorial_id=tutorial_id,
        payload=payload,
    )


@router.post(
    "/{tutorial_id}/video",
    response_model=AdminTutorialResponse,
    status_code=status.HTTP_200_OK,
    summary="Thay thế tệp video của tutorial",
)
async def replace_tutorial_video(
    tutorial_id: int,
    video: UploadFile = File(..., description="Tệp video MP4 mới"),
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminTutorialResponse:
    service = TutorialService(db)
    return await service.replace_tutorial_video(
        tutorial_id=tutorial_id,
        video_file=video,
    )


@router.delete(
    "/{tutorial_id}",
    status_code=status.HTTP_200_OK,
    summary="Xóa vĩnh viễn tutorial",
)
async def delete_tutorial(
    tutorial_id: int,
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    service = TutorialService(db)
    return await service.delete_tutorial(tutorial_id=tutorial_id)
