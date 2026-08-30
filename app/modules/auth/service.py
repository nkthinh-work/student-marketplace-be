import logging
from datetime import datetime, timezone
from typing import Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException, status

from app.modules.users.models import User, UserStatus, UserRole
from app.modules.users.repository import UserRepository

logger = logging.getLogger("app")


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.user_repo = UserRepository(db)

    async def get_or_create_user_from_token_payload(self, token_payload: dict[str, Any]) -> User:
        """
        Resolves a verified Firebase token payload to an internal User.
        If the user identity exists, loads and returns the User.
        If this is the first login for this Firebase UID, atomically provisions
        a new User record and associated UserAuthIdentity record.
        Handles race conditions gracefully.
        """
        provider_uid = token_payload.get("uid")
        if not provider_uid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token payload missing required identity identifier.",
            )

        provider = "FIREBASE"

        # 1. Tìm identity hiện có
        user = await self.user_repo.get_by_provider_uid(provider, provider_uid)
        if user:
            try:
                user.last_active_at = datetime.now(timezone.utc).replace(tzinfo=None)

                # Đồng bộ avatar_url từ Google/Firebase nếu có thay đổi
                provider_avatar = token_payload.get("picture")
                if provider_avatar and provider_avatar != user.avatar_url:
                    user.avatar_url = provider_avatar

                await self.db.commit()
                await self.db.refresh(user)
            except Exception as e:
                logger.warning(f"Failed to update last_active_at / avatar for user {user.user_id}: {e}")
                await self.db.rollback()
            return user

        # 2. Provision user mới từ payload đã verify
        email = token_payload.get("email")
        if not email:
            # Fallback email khi Firebase token không có email (phone/anonymous)
            email = f"{provider_uid}@firebase.user"

        full_name = token_payload.get("name") or email.split("@")[0]
        avatar_url = token_payload.get("picture")

        try:
            existing_user_by_email = await self.user_repo.get_by_email(email)
            if existing_user_by_email:
                # Link identity Firebase mới vào user đã có email tương ứng
                from app.modules.users.models import UserAuthIdentity
                identity = UserAuthIdentity(
                    user_id=existing_user_by_email.user_id,
                    provider=provider,
                    provider_uid=provider_uid,
                )
                self.db.add(identity)

                # Đồng bộ avatar nếu user cũ chưa có hoặc avatar mới khác
                if avatar_url and avatar_url != existing_user_by_email.avatar_url:
                    existing_user_by_email.avatar_url = avatar_url

                await self.db.commit()
                await self.db.refresh(existing_user_by_email)
                logger.info(f"Linked Firebase UID {provider_uid} to existing user {existing_user_by_email.user_id}")
                return existing_user_by_email

            # Tạo user và identity mới trong transaction
            new_user = await self.user_repo.create_user_with_identity(
                email=email,
                full_name=full_name,
                avatar_url=avatar_url,
                provider=provider,
                provider_uid=provider_uid,
                role=UserRole.STUDENT.value,
                status=UserStatus.ACTIVE,
            )
            await self.db.commit()
            await self.db.refresh(new_user)
            logger.info(f"Provisioned new user {new_user.user_id} for Firebase UID {provider_uid}")
            return new_user

        except IntegrityError as e:
            # Xử lý race condition khi có request đồng thời tạo/link identity
            logger.warning(f"IntegrityError during first-login provisioning for UID {provider_uid}: {e}")
            await self.db.rollback()

            user = await self.user_repo.get_by_provider_uid(provider, provider_uid)
            if user:
                return user

            user = await self.user_repo.get_by_email(email)
            if user:
                return user

            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User account provisioning conflict. Please retry.",
            )
