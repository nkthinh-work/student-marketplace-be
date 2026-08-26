from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_active_user
from app.modules.users.models import User
from app.modules.users.schemas import UserResponse, UserUpdate
from app.modules.users.service import UserService

router = APIRouter(prefix="/users", tags=["Users"])


@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Get current user profile",
)
async def get_my_profile(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """
    Retrieve the profile of the currently authenticated active user.
    """
    return current_user


@router.patch(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Update current user profile",
)
async def update_my_profile(
    payload: UserUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Update profile fields (full_name, phone, avatar_url, bio, default_meetup_area)
    for the currently authenticated active user.
    """
    user_service = UserService(db)
    updated_user = await user_service.update_profile(current_user, payload)
    return updated_user
