import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.models import Notification
from app.modules.notifications.repository import NotificationRepository
from app.modules.notifications.schemas import (
    NotificationListResponse,
    NotificationResponse,
    UnreadCountResponse,
)

logger = logging.getLogger("app.notifications")


def format_notification(n: Notification) -> NotificationResponse:
    return NotificationResponse(
        notification_id=n.notification_id,
        type=n.type,
        title=n.title,
        body=n.body,
        ref_type=n.ref_type,
        ref_id=n.ref_id,
        is_read=n.is_read,
        created_at=n.created_at,
    )


class NotificationService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = NotificationRepository(db)

    async def create_notification(
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
        Create a durable notification row. Does NOT commit.
        The calling business service owns the transaction boundary.
        """
        return await self.repo.create(
            user_id=user_id,
            type=type,
            title=title,
            body=body,
            ref_type=ref_type,
            ref_id=ref_id,
        )

    async def list_notifications(
        self,
        user_id: int,
        *,
        limit: int = 20,
        cursor: Optional[str] = None,
        unread_only: bool = False,
    ) -> NotificationListResponse:
        limit = max(1, min(limit, 50))
        cursor_data = self.repo.decode_cursor(cursor) if cursor else None

        notifications = await self.repo.list_for_user(
            user_id,
            limit=limit,
            cursor_data=cursor_data,
            unread_only=unread_only,
        )

        has_more = len(notifications) > limit
        if has_more:
            notifications = notifications[:limit]

        next_cursor = None
        if has_more and notifications:
            last = notifications[-1]
            next_cursor = self.repo.encode_cursor(last.created_at, last.notification_id)

        return NotificationListResponse(
            items=[format_notification(n) for n in notifications],
            next_cursor=next_cursor,
            has_more=has_more,
        )

    async def get_unread_count(self, user_id: int) -> UnreadCountResponse:
        count = await self.repo.count_unread(user_id)
        return UnreadCountResponse(count=count)

    async def mark_read(self, notification_id: int, user_id: int) -> bool:
        """Returns True if notification existed for user. Idempotent."""
        return await self.repo.mark_read(notification_id, user_id)

    async def mark_all_read(self, user_id: int) -> int:
        """Returns number of rows updated. Idempotent."""
        return await self.repo.mark_all_read(user_id)
