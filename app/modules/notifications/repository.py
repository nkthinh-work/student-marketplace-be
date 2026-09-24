import base64
import json
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.models import Notification

logger = logging.getLogger("app.notifications")


class NotificationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def encode_cursor(created_at: datetime, notification_id: int) -> str:
        cursor_data = {
            "created_at": created_at.isoformat(),
            "notification_id": notification_id,
        }
        json_str = json.dumps(cursor_data)
        return base64.urlsafe_b64encode(json_str.encode()).decode()

    @staticmethod
    def decode_cursor(cursor_str: str) -> Optional[dict]:
        try:
            json_str = base64.urlsafe_b64decode(cursor_str.encode()).decode()
            data = json.loads(json_str)
            data["created_at"] = datetime.fromisoformat(data["created_at"])
            return data
        except Exception:
            return None

    async def create(
        self,
        *,
        user_id: int,
        type: str,
        title: str,
        body: Optional[str] = None,
        ref_type: Optional[str] = None,
        ref_id: Optional[int] = None,
    ) -> Notification:
        """
        Insert a notification row. Does NOT commit — caller owns the transaction.
        """
        notification = Notification(
            user_id=user_id,
            type=type,
            title=title,
            body=body,
            ref_type=ref_type,
            ref_id=ref_id,
        )
        self.db.add(notification)
        await self.db.flush()
        return notification

    async def list_for_user(
        self,
        user_id: int,
        *,
        limit: int = 20,
        cursor_data: Optional[dict] = None,
        unread_only: bool = False,
    ) -> list[Notification]:
        stmt = select(Notification).where(Notification.user_id == user_id)

        if unread_only:
            stmt = stmt.where(Notification.is_read.is_(False))

        if cursor_data:
            c_created = cursor_data["created_at"]
            c_id = cursor_data["notification_id"]
            stmt = stmt.where(
                (Notification.created_at < c_created)
                | (
                    (Notification.created_at == c_created)
                    & (Notification.notification_id < c_id)
                )
            )

        stmt = stmt.order_by(
            desc(Notification.created_at),
            desc(Notification.notification_id),
        ).limit(limit + 1)

        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def count_unread(self, user_id: int) -> int:
        stmt = (
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.is_read.is_(False),
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one()

    async def get_user_notification(
        self, notification_id: int, user_id: int
    ) -> Optional[Notification]:
        stmt = select(Notification).where(
            Notification.notification_id == notification_id,
            Notification.user_id == user_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def mark_read(self, notification_id: int, user_id: int) -> bool:
        """
        Idempotent mark-one-read. Returns True if notification existed for user.
        """
        stmt = (
            update(Notification)
            .where(
                Notification.notification_id == notification_id,
                Notification.user_id == user_id,
            )
            .values(is_read=True)
        )
        result = await self.db.execute(stmt)
        await self.db.commit()
        return result.rowcount > 0

    async def mark_all_read(self, user_id: int) -> int:
        """
        Set-based mark-all-read. Returns number of rows updated.
        """
        stmt = (
            update(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.is_read.is_(False),
            )
            .values(is_read=True)
        )
        result = await self.db.execute(stmt)
        await self.db.commit()
        return result.rowcount
