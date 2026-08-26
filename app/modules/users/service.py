import logging
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from app.modules.users.models import User
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import UserUpdate

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

        # Chặn cập nhật các trường nhạy cảm/hệ thống
        disallowed_fields = {"user_id", "email", "role", "status", "created_at", "updated_at", "last_active_at"}
        filtered_data = {k: v for k, v in update_data.items() if k not in disallowed_fields}

        updated_user = await self.user_repo.update_user(user, filtered_data)
        await self.db.commit()
        await self.db.refresh(updated_user)
        return updated_user
