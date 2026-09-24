from datetime import datetime
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.users.capability_models import (
    CapabilityType,
    UserCapabilityRestriction,
)
from app.modules.users.capability_repository import CapabilityRestrictionRepository
from app.modules.users.models import User, UserRole, UserStatus


class CapabilityService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = CapabilityRestrictionRepository(db)

    async def get_effective_restrictions(
        self, user_id: int, now_utc: datetime
    ) -> list[UserCapabilityRestriction]:
        return await self.repo.get_active_restrictions_by_user(user_id, now_utc)

    async def can_user_buy(self, user: User | int, now_utc: datetime) -> bool:
        if isinstance(user, int):
            u = await self.db.get(User, user)
            if not u:
                return False
            user = u
        user_status = user.status.value if hasattr(user.status, "value") else str(user.status)
        if user_status == UserStatus.BANNED.value or user_status == UserStatus.INACTIVE.value:
            return False
        if user.role == UserRole.ADMIN.value:
            return True
        restrictions = await self.repo.get_active_restrictions_by_user(user.user_id, now_utc)
        return not any(r.capability == CapabilityType.BUY.value for r in restrictions)

    async def can_user_sell(self, user: User | int, now_utc: datetime) -> bool:
        if isinstance(user, int):
            u = await self.db.get(User, user)
            if not u:
                return False
            user = u
        user_status = user.status.value if hasattr(user.status, "value") else str(user.status)
        if user_status == UserStatus.BANNED.value or user_status == UserStatus.INACTIVE.value:
            return False
        if user.role == UserRole.ADMIN.value:
            return True
        restrictions = await self.repo.get_active_restrictions_by_user(user.user_id, now_utc)
        return not any(r.capability == CapabilityType.SELL.value for r in restrictions)

    async def get_user_capabilities(
        self, user: User | int, now_utc: datetime
    ) -> tuple[bool, bool, list[UserCapabilityRestriction]]:
        """
        Determines can_buy, can_sell, and active restrictions using a single bounded query.
        """
        if isinstance(user, int):
            u = await self.db.get(User, user)
            if not u:
                return False, False, []
            user = u
        user_status = user.status.value if hasattr(user.status, "value") else str(user.status)
        if user_status == UserStatus.BANNED.value or user_status == UserStatus.INACTIVE.value:
            return False, False, []

        if user.role == UserRole.ADMIN.value:
            return True, True, []

        restrictions = await self.repo.get_active_restrictions_by_user(user.user_id, now_utc)
        can_buy = not any(r.capability == CapabilityType.BUY.value for r in restrictions)
        can_sell = not any(r.capability == CapabilityType.SELL.value for r in restrictions)
        return can_buy, can_sell, restrictions

