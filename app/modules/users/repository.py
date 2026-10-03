import uuid
from datetime import datetime
from typing import Optional, Any
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.users.models import User, UserAuthIdentity, UserStatus, UserRole


class UserRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, user_id: int) -> Optional[User]:
        stmt = (
            select(User)
            .options(selectinload(User.auth_identity))
            .where(User.user_id == user_id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_public_id(self, public_id: Any) -> Optional[User]:
        if not isinstance(public_id, uuid.UUID):
            try:
                public_id = uuid.UUID(str(public_id))
            except (ValueError, TypeError, AttributeError):
                return None
        stmt = (
            select(User)
            .options(selectinload(User.auth_identity))
            .where(User.public_id == public_id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()


    async def get_by_id_for_update(self, user_id: int) -> Optional[User]:
        stmt = (
            select(User)
            .where(User.user_id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> Optional[User]:
        stmt = (
            select(User)
            .options(selectinload(User.auth_identity))
            .where(User.email == email)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_provider_uid(self, provider: str, provider_uid: str) -> Optional[User]:
        stmt = (
            select(User)
            .join(UserAuthIdentity, User.user_id == UserAuthIdentity.user_id)
            .options(selectinload(User.auth_identity))
            .where(
                UserAuthIdentity.provider == provider,
                UserAuthIdentity.provider_uid == provider_uid,
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_auth_identity(self, provider: str, provider_uid: str) -> Optional[UserAuthIdentity]:
        stmt = select(UserAuthIdentity).where(
            UserAuthIdentity.provider == provider,
            UserAuthIdentity.provider_uid == provider_uid,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_user_with_identity(
        self,
        email: str,
        full_name: str,
        avatar_url: Optional[str],
        provider: str,
        provider_uid: str,
        role: str = UserRole.STUDENT.value,
        status: UserStatus = UserStatus.ACTIVE,
    ) -> User:
        user = User(
            email=email,
            full_name=full_name,
            avatar_url=avatar_url,
            role=role,
            status=status,
            last_active_at=func.now(),
        )
        self.db.add(user)
        await self.db.flush()  # Flush to generate user.user_id

        identity = UserAuthIdentity(
            user_id=user.user_id,
            provider=provider,
            provider_uid=provider_uid,
        )
        self.db.add(identity)
        await self.db.flush()

        return user

    async def update_user(self, user: User, update_data: dict[str, Any]) -> User:
        for field, value in update_data.items():
            if hasattr(user, field):
                setattr(user, field, value)
        await self.db.flush()
        return user

    async def update_last_active(self, user_id: int) -> None:
        stmt = (
            update(User)
            .where(User.user_id == user_id)
            .values(last_active_at=func.now())
        )
        await self.db.execute(stmt)
        await self.db.flush()

    async def update_bank_account(
        self,
        user: User,
        bank_bin: str,
        bank_account_number: str,
        bank_account_name: str,
    ) -> User:
        user.bank_bin = bank_bin
        user.bank_account_number = bank_account_number
        user.bank_account_name = bank_account_name
        await self.db.flush()
        return user

    async def clear_bank_account(self, user: User) -> User:
        user.bank_bin = None
        user.bank_account_number = None
        user.bank_account_name = None
        await self.db.flush()
        return user
