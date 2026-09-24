import base64
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.feedback.models import SiteFeedback, SiteFeedbackAttachment
from app.modules.users.models import User, UserStatus


def encode_feedback_cursor(created_at: datetime, feedback_id: int) -> str:
    """Encodes created_at (ISO format) and feedback_id into an opaque Base64 string."""
    payload = f"{created_at.isoformat()}|{feedback_id}"
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("utf-8")


def decode_feedback_cursor(cursor_str: str) -> Tuple[datetime, int]:
    """
    Decodes an opaque Base64 cursor string into (created_at, feedback_id).
    Raises ValueError if malformed.
    """
    try:
        raw = base64.urlsafe_b64decode(cursor_str.encode("utf-8")).decode("utf-8")
        parts = raw.split("|")
        if len(parts) != 2:
            raise ValueError("Invalid cursor format")
        created_at = datetime.fromisoformat(parts[0])
        feedback_id = int(parts[1])
        return created_at, feedback_id
    except Exception as e:
        raise ValueError("Invalid cursor") from e


async def create_feedback(
    session: AsyncSession,
    user_id: int,
    content: str,
) -> SiteFeedback:
    feedback = SiteFeedback(
        user_id=user_id,
        content=content,
    )
    session.add(feedback)
    await session.flush()
    return feedback


async def add_attachments(
    session: AsyncSession,
    feedback_id: int,
    attachments_data: List[Dict[str, Any]],
) -> List[SiteFeedbackAttachment]:
    created = []
    for item in attachments_data:
        attachment = SiteFeedbackAttachment(
            feedback_id=feedback_id,
            kind=item["kind"],
            media_url=item["media_url"],
            storage_key=item["storage_key"],
            mime_type=item["mime_type"],
            size_bytes=item["size_bytes"],
            duration_ms=item.get("duration_ms"),
        )
        session.add(attachment)
        created.append(attachment)
    await session.flush()
    return created


async def list_public_feedbacks(
    session: AsyncSession,
    limit: int = 20,
    cursor: Optional[str] = None,
) -> Tuple[List[SiteFeedback], Optional[str], bool]:
    safe_limit = min(max(1, limit), 50)
    stmt = (
        select(SiteFeedback)
        .join(User, SiteFeedback.user_id == User.user_id)
        .where(User.status.in_([UserStatus.ACTIVE, "ACTIVE"]))
        .order_by(
            desc(SiteFeedback.created_at),
            desc(SiteFeedback.feedback_id),
        )
    )

    if cursor:
        cursor_created_at, cursor_id = decode_feedback_cursor(cursor)
        stmt = stmt.where(
            or_(
                SiteFeedback.created_at < cursor_created_at,
                and_(
                    SiteFeedback.created_at == cursor_created_at,
                    SiteFeedback.feedback_id < cursor_id,
                ),
            )
        )

    stmt = stmt.limit(safe_limit + 1)
    res = await session.execute(stmt)
    records = list(res.scalars().all())

    has_more = len(records) > safe_limit
    items = records[:safe_limit]

    next_cursor = None
    if has_more and items:
        last_item = items[-1]
        next_cursor = encode_feedback_cursor(last_item.created_at, last_item.feedback_id)

    return items, next_cursor, has_more


async def list_user_feedbacks(
    session: AsyncSession,
    user_id: int,
    limit: int = 20,
    cursor: Optional[str] = None,
) -> Tuple[List[SiteFeedback], Optional[str], bool]:
    safe_limit = min(max(1, limit), 50)
    stmt = (
        select(SiteFeedback)
        .where(SiteFeedback.user_id == user_id)
        .options(selectinload(SiteFeedback.attachments))
        .order_by(
            desc(SiteFeedback.created_at),
            desc(SiteFeedback.feedback_id),
        )
    )

    if cursor:
        cursor_created_at, cursor_id = decode_feedback_cursor(cursor)
        stmt = stmt.where(
            or_(
                SiteFeedback.created_at < cursor_created_at,
                and_(
                    SiteFeedback.created_at == cursor_created_at,
                    SiteFeedback.feedback_id < cursor_id,
                ),
            )
        )

    stmt = stmt.limit(safe_limit + 1)
    res = await session.execute(stmt)
    records = list(res.scalars().all())

    has_more = len(records) > safe_limit
    items = records[:safe_limit]

    next_cursor = None
    if has_more and items:
        last_item = items[-1]
        next_cursor = encode_feedback_cursor(last_item.created_at, last_item.feedback_id)

    return items, next_cursor, has_more


async def list_admin_feedbacks(
    session: AsyncSession,
    limit: int = 20,
    cursor: Optional[str] = None,
) -> Tuple[List[SiteFeedback], Optional[str], bool]:
    safe_limit = min(max(1, limit), 50)
    stmt = (
        select(SiteFeedback)
        .options(
            selectinload(SiteFeedback.user),
            selectinload(SiteFeedback.attachments),
        )
        .order_by(
            desc(SiteFeedback.created_at),
            desc(SiteFeedback.feedback_id),
        )
    )

    if cursor:
        cursor_created_at, cursor_id = decode_feedback_cursor(cursor)
        stmt = stmt.where(
            or_(
                SiteFeedback.created_at < cursor_created_at,
                and_(
                    SiteFeedback.created_at == cursor_created_at,
                    SiteFeedback.feedback_id < cursor_id,
                ),
            )
        )

    stmt = stmt.limit(safe_limit + 1)
    res = await session.execute(stmt)
    records = list(res.scalars().all())

    has_more = len(records) > safe_limit
    items = records[:safe_limit]

    next_cursor = None
    if has_more and items:
        last_item = items[-1]
        next_cursor = encode_feedback_cursor(last_item.created_at, last_item.feedback_id)

    return items, next_cursor, has_more


async def get_by_id(
    session: AsyncSession,
    feedback_id: int,
    eager_load: bool = True,
    for_update: bool = False,
) -> Optional[SiteFeedback]:
    stmt = select(SiteFeedback).where(SiteFeedback.feedback_id == feedback_id)
    if eager_load:
        stmt = stmt.options(
            selectinload(SiteFeedback.user),
            selectinload(SiteFeedback.attachments),
        )
    if for_update:
        stmt = stmt.with_for_update()
    res = await session.execute(stmt)
    return res.scalar_one_or_none()


async def get_attachment_by_id(
    session: AsyncSession,
    attachment_id: int,
) -> Optional[SiteFeedbackAttachment]:
    stmt = (
        select(SiteFeedbackAttachment)
        .where(SiteFeedbackAttachment.attachment_id == attachment_id)
        .options(selectinload(SiteFeedbackAttachment.feedback))
    )
    res = await session.execute(stmt)
    return res.scalar_one_or_none()


async def delete_feedback(
    session: AsyncSession,
    feedback: SiteFeedback,
) -> None:
    await session.delete(feedback)
