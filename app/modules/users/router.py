from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.banks import SUPPORTED_BANKS, BankInfo
from app.core.database import get_db
from app.modules.auth.dependencies import get_current_active_user, get_current_user
from app.modules.users.models import User, UserStatus
from datetime import datetime, timezone
from app.modules.users.capability_service import CapabilityService
from app.modules.users.schemas import (
    BankAccountResponse,
    BankAccountUpdate,
    PublicUserProfileResponse,
    SoldProductListResponse,
    UserAccessStatusResponse,
    UserCapabilityRestrictionResponse,
    UserResponse,
    UserUpdate,
)
from app.modules.conversations.schemas import UserSearchResponse
from app.modules.users.service import UserService

router = APIRouter(prefix="/users", tags=["Users"])


@router.get(
    "/search",
    response_model=List[UserSearchResponse],
    status_code=status.HTTP_200_OK,
    summary="Tìm kiếm người dùng công khai (cho mời nhóm)",
)
async def search_users(
    q: str = Query(..., min_length=2, description="Từ khóa tìm kiếm tên người dùng"),
    limit: int = Query(20, ge=1, le=50),
    conversation_id: Optional[int] = Query(None, description="Loại trừ thành viên nhóm hiện tại"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> List[UserSearchResponse]:
    """
    Tìm kiếm người dùng an toàn theo tên, chỉ trả về user_id, full_name, avatar_url.
    Không để lộ email, SĐT hay tài khoản ngân hàng.
    """
    from app.modules.conversations.service import ConversationService
    conv_service = ConversationService(db)
    return await conv_service.search_users(
        current_user, query=q, limit=limit, conversation_id=conversation_id
    )


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
    "/me/access-status",
    response_model=UserAccessStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Lấy trạng thái truy cập tài khoản (cho phép tài khoản bị khóa/chưa kích hoạt)",
)
async def get_my_access_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserAccessStatusResponse:
    """
    Xác định trạng thái truy cập tài khoản có tính định danh máy.
    Chấp nhận danh tính Firebase hợp lệ kể cả khi người dùng bị BANNED hoặc INACTIVE.
    Không để lộ thông tin nhạy cảm.
    """
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    capability_service = CapabilityService(db)
    can_buy, can_sell, restrictions = await capability_service.get_user_capabilities(current_user, now_utc)

    return UserAccessStatusResponse(
        user_id=current_user.user_id,
        status=current_user.status.value if hasattr(current_user.status, "value") else str(current_user.status),
        role=current_user.role,
        can_buy=can_buy,
        can_sell=can_sell,
        active_restrictions=[
            UserCapabilityRestrictionResponse(
                capability=r.capability,
                expires_at=r.expires_at,
            )
            for r in restrictions
        ],
    )


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
    Update profile fields (full_name, phone, show_phone_publicly, social_links, bio, delivery_area)
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


@router.get(
    "/{user_id}",
    response_model=PublicUserProfileResponse,
    status_code=status.HTTP_200_OK,
    summary="Lấy thông tin hồ sơ công khai của người dùng",
)
async def get_public_user_profile(
    user_id: int,
    db: AsyncSession = Depends(get_db),
) -> PublicUserProfileResponse:
    """
    Trả về thông tin hồ sơ công khai của người dùng (tên, avatar, bio, phạm vi giao/nhận, mạng xã hội, thống kê bán hàng).
    Không làm lộ các thông tin riêng tư / nhạy cảm (email, sđt chưa công khai, tài khoản ngân hàng).
    """
    user_service = UserService(db)
    return await user_service.get_public_profile(user_id)


@router.get(
    "/{user_id}/sold-products",
    response_model=SoldProductListResponse,
    status_code=status.HTTP_200_OK,
    summary="Lấy danh sách lịch sử sản phẩm đã bán hoàn tất",
)
async def get_user_sold_products(
    user_id: int,
    db: AsyncSession = Depends(get_db),
) -> SoldProductListResponse:
    """
    Trả về lịch sử sản phẩm đã bán hoàn tất (COMPLETED orders) của người bán.
    Sanitized: Chỉ hiển thị tên sản phẩm, ảnh đại diện, số lượng đã bán, không để lộ thông tin đơn hàng hay người mua.
    """
    user_service = UserService(db)
    return await user_service.get_sold_products(user_id)

