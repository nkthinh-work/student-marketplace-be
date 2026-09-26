from typing import Optional
from fastapi import APIRouter, Depends, status, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_active_user
from app.modules.users.models import User
from app.modules.daily_needs.schemas import (
    DailyNeedResponse,
    DailyNeedListResponse,
    DailyNeedCreateOrUpdate,
    DailyNeedPublicResponse,
    DailyNeedSummaryResponse,
)
from app.modules.daily_needs.service import DailyNeedService

router = APIRouter(prefix="/daily-needs", tags=["daily-needs"])



@router.get(
    "/recent",
    response_model=DailyNeedListResponse,
    summary="Danh sách nhật ký gần nhất trên toàn hệ thống (tối đa 10)",
)
async def get_recent_daily_needs(
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
) -> DailyNeedListResponse:
    service = DailyNeedService(db)
    return await service.get_recent_public_notes(limit=limit)


@router.get(
    "/today",
    response_model=DailyNeedListResponse,
    summary="Danh sách nhu cầu hôm nay (tối đa 10)",
)
async def get_today_daily_needs(
    db: AsyncSession = Depends(get_db),
) -> DailyNeedListResponse:
    service = DailyNeedService(db)
    return await service.get_today_public_notes(limit=10)


@router.get(
    "/me/today",
    response_model=Optional[DailyNeedResponse],
    summary="Nhu cầu hôm nay của tôi (hoặc null)",
)
async def get_my_today_daily_need(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Optional[DailyNeedResponse]:
    service = DailyNeedService(db)
    return await service.get_my_today_note(current_user)


@router.get(
    "/me/summary",
    response_model=DailyNeedSummaryResponse,
    summary="Tóm tắt nhật ký và chuỗi ngày của tôi",
)
async def get_my_daily_need_summary(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> DailyNeedSummaryResponse:
    service = DailyNeedService(db)
    return await service.get_my_summary(current_user)


@router.get(
    "/users/{user_id}/today",
    response_model=Optional[DailyNeedPublicResponse],
    summary="Nhật ký hôm nay của người dùng công khai",
)
async def get_user_today_daily_need(
    user_id: int,
    db: AsyncSession = Depends(get_db),
) -> Optional[DailyNeedPublicResponse]:
    service = DailyNeedService(db)
    return await service.get_user_today_public_note(user_id)



@router.put(
    "/me/today",
    response_model=DailyNeedResponse,
    summary="Đăng hoặc cập nhật nhu cầu hôm nay của tôi",
)
async def upsert_my_today_daily_need(
    payload: DailyNeedCreateOrUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> DailyNeedResponse:
    service = DailyNeedService(db)
    return await service.upsert_my_today_note(current_user, payload)


@router.delete(
    "/me/today",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Xóa nhu cầu hôm nay của tôi",
)
async def delete_my_today_daily_need(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    service = DailyNeedService(db)
    await service.delete_my_today_note(current_user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
