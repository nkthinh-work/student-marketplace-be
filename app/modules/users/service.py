import logging
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from app.core.banks import get_bank_by_bin, resolve_bank_bin
from app.modules.users.models import User
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import BankAccountResponse, BankAccountUpdate, UserUpdate

logger = logging.getLogger("app")


class UserService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.user_repo = UserRepository(db)

    async def get_user_by_id(self, user_id: int) -> Optional[User]:
        return await self.user_repo.get_by_id(user_id)

    async def update_profile(self, user: User, payload: UserUpdate) -> User:
        update_data = payload.model_dump(exclude_unset=True)
        if not update_data:
            return user

        # Chặn cập nhật các trường nhạy cảm/hệ thống và trường do Google sync quản lý
        disallowed_fields = {
            "user_id",
            "email",
            "role",
            "status",
            "avatar_url",
            "bank_bin",
            "bank_account_number",
            "bank_account_name",
            "created_at",
            "updated_at",
            "last_active_at",
        }
        filtered_data = {k: v for k, v in update_data.items() if k not in disallowed_fields}

        updated_user = await self.user_repo.update_user(user, filtered_data)
        await self.db.commit()
        await self.db.refresh(updated_user)
        return updated_user

    async def get_bank_account(self, user: User) -> Optional[BankAccountResponse]:
        if not user.bank_bin or not user.bank_account_number or not user.bank_account_name:
            return None

        bank_info = get_bank_by_bin(user.bank_bin)
        return BankAccountResponse(
            bank_bin=user.bank_bin,
            bank_code=bank_info.code if bank_info else user.bank_bin,
            bank_name=bank_info.name if bank_info else "",
            bank_short_name=bank_info.short_name if bank_info else (bank_info.code if bank_info else user.bank_bin),
            account_number=user.bank_account_number,
            account_name=user.bank_account_name,
        )

    async def update_bank_account(self, user: User, payload: BankAccountUpdate) -> BankAccountResponse:
        resolved_bin = resolve_bank_bin(payload.bank_bin)
        if not resolved_bin:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ngân hàng không hợp lệ hoặc không được hỗ trợ.",
            )

        bank_info = get_bank_by_bin(resolved_bin)
        clean_account_number = payload.account_number.strip()
        clean_account_name = payload.account_name.strip()

        # Update and commit in transaction
        await self.user_repo.update_bank_account(
            user=user,
            bank_bin=resolved_bin,
            bank_account_number=clean_account_number,
            bank_account_name=clean_account_name,
        )
        await self.db.commit()
        await self.db.refresh(user)

        return BankAccountResponse(
            bank_bin=user.bank_bin,
            bank_code=bank_info.code if bank_info else user.bank_bin,
            bank_name=bank_info.name if bank_info else "",
            bank_short_name=bank_info.short_name if bank_info else user.bank_bin,
            account_number=user.bank_account_number,
            account_name=user.bank_account_name,
        )

    async def delete_bank_account(self, user: User) -> None:
        await self.user_repo.clear_bank_account(user)
        await self.db.commit()
        await self.db.refresh(user)
