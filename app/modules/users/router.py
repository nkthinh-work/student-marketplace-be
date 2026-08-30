from typing import List, Optional
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.banks import SUPPORTED_BANKS, BankInfo
from app.core.database import get_db
from app.modules.auth.dependencies import get_current_active_user
from app.modules.users.models import User
from app.modules.users.schemas import (
    BankAccountResponse,
    BankAccountUpdate,
    UserResponse,
    UserUpdate,
)
from app.modules.users.service import UserService

router = APIRouter(prefix="/users", tags=["Users"])


@router.get(
    "/banks",
    response_model=List[BankInfo],
    status_code=status.HTTP_200_OK,
    summary="Lấy danh sách ngân hàng Việt Nam được hỗ trợ (VietQR/NAPAS)",
)
async def get_supported_banks() -> List[BankInfo]:
    """
    Trả về danh sách ngân hàng chính thức tại Việt Nam bao gồm BIN, Code, tên viết tắt và tên đầy đủ.
    """
    return SUPPORTED_BANKS


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
    Update profile fields (full_name, phone, bio, default_meetup_area)
    for the currently authenticated active user. Avatar is managed via Google identity sync.
    """
    user_service = UserService(db)
    updated_user = await user_service.update_profile(current_user, payload)
    return updated_user


@router.get(
    "/me/bank-account",
    response_model=Optional[BankAccountResponse],
    status_code=status.HTTP_200_OK,
    summary="Lấy thông tin tài khoản nhận tiền của người dùng hiện tại",
)
async def get_my_bank_account(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Optional[BankAccountResponse]:
    """
    Trả về thông tin tài khoản nhận tiền của người dùng hiện tại, hoặc null nếu chưa thiết lập.
    """
    user_service = UserService(db)
    return await user_service.get_bank_account(current_user)


@router.put(
    "/me/bank-account",
    response_model=BankAccountResponse,
    status_code=status.HTTP_200_OK,
    summary="Thiết lập / Cập nhật tài khoản nhận tiền của người dùng hiện tại",
)
async def update_my_bank_account(
    payload: BankAccountUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> BankAccountResponse:
    """
    Tạo mới hoặc ghi đè tài khoản nhận tiền duy nhất (MVP) cho người dùng hiện tại.
    """
    user_service = UserService(db)
    return await user_service.update_bank_account(current_user, payload)


@router.delete(
    "/me/bank-account",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Xóa tài khoản nhận tiền của người dùng hiện tại",
)
async def delete_my_bank_account(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Xóa tài khoản nhận tiền của người dùng hiện tại. Không ảnh hưởng tới các đơn hàng đã chốt snapshot trước đó.
    """
    user_service = UserService(db)
    await user_service.delete_bank_account(current_user)
