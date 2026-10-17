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

from app.modules.notifications.models import Notification, NotificationType

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


async def safe_dispatch_push_notification(
    user_id: int,
    title: str,
    body: str,
    data: Optional[dict[str, str]] = None,
) -> None:
    """Best-effort post-commit Web Push dispatch to registered FCM tokens for user."""
    try:
        from app.core.database import SessionLocal
        from app.integrations.firebase import send_multicast_push
        from app.modules.notifications.repository import NotificationRepository

        async with SessionLocal() as session:
            repo = NotificationRepository(session)
            tokens = await repo.get_device_tokens_for_user(user_id)
            if not tokens:
                return

            import asyncio
            stale_tokens = await asyncio.wait_for(
                asyncio.to_thread(
                    send_multicast_push,
                    tokens=tokens,
                    title=title,
                    body=body,
                    data=data,
                ),
                timeout=10.0,
            )
            if stale_tokens:
                await repo.delete_stale_device_tokens(stale_tokens)
    except Exception as err:
        logger.warning("Failed to dispatch push notification to user %s: %s", user_id, err)


async def safe_publish_user_notification(user_id: int, notif_dto: NotificationResponse) -> None:
    """Best-effort post-commit realtime notification dispatch isolated per recipient."""
    # 1. In-App WebSocket dispatch
    try:
        from app.modules.orders.websocket import publish_user_event
        await publish_user_event(
            user_id,
            {
                "type": "NOTIFICATION_CREATED",
                "notification": notif_dto.model_dump(mode="json"),
            },
        )
    except Exception as err:
        logger.warning("Failed to publish NOTIFICATION_CREATED to user %s: %s", user_id, err)

    # 2. Web Push notification dispatch
    push_data = {
        "notification_id": str(notif_dto.notification_id),
        "type": notif_dto.type,
        "ref_type": str(notif_dto.ref_type or ""),
        "ref_id": str(notif_dto.ref_id or ""),
    }
    await safe_dispatch_push_notification(
        user_id=user_id,
        title=notif_dto.title,
        body=notif_dto.body or "",
        data=push_data,
    )


async def dispatch_notification_snapshots(
    snapshots: list[tuple[int, NotificationResponse]],
) -> None:
    """Dispatches multiple notification snapshots sequentially and safely."""
    for user_id, notif_dto in snapshots:
        await safe_publish_user_notification(user_id, notif_dto)


class NotificationService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = NotificationRepository(db)

    async def subscribe_push_token(
        self, user_id: int, fcm_token: str, device_info: Optional[str] = None
    ) -> None:
        """Register or update FCM device token for authenticated user."""
        await self.repo.upsert_device_token(user_id, fcm_token, device_info)

    async def unsubscribe_push_token(self, user_id: int, fcm_token: str) -> bool:
        """Unregister FCM device token for authenticated user."""
        return await self.repo.delete_device_token(user_id, fcm_token)

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

    async def get_active_admin_ids(self) -> list[int]:
        """Fetch all ACTIVE Admin user IDs."""
        return await self.repo.get_active_admin_ids()

    async def notify_admins(
        self,
        *,
        title: str,
        body: Optional[str] = None,
        ref_type: Optional[str] = None,
        ref_id: Optional[int] = None,
    ) -> list[tuple[int, NotificationResponse]]:
        """
        Create durable SYSTEM notifications for all ACTIVE Admins.
        Does NOT commit — caller owns transaction boundary.
        Returns list of (admin_id, NotificationResponse) snapshots for post-commit dispatch.
        """
        admin_ids = await self.get_active_admin_ids()
        snapshots: list[tuple[int, NotificationResponse]] = []
        for admin_id in admin_ids:
            notif = await self.repo.create(
                user_id=admin_id,
                type=NotificationType.SYSTEM.value,
                title=title,
                body=body,
                ref_type=ref_type,
                ref_id=ref_id,
            )
            snapshots.append((admin_id, format_notification(notif)))
        return snapshots

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

    async def delete_notification(self, notification_id: int, user_id: int) -> bool:
        """Returns True if notification existed for user and was deleted."""
        return await self.repo.delete_user_notification(notification_id, user_id)
