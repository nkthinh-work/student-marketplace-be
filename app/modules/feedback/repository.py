import base64
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, asc, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.feedback.models import (
    SiteFeedback,
    SiteFeedbackAttachment,
    SupportContribution,
    SupportClaim,
    SupportClaimStatus,
)
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


# ======================================================================
# SUPPORT CONTRIBUTIONS REPOSITORY
# ======================================================================

def encode_support_cursor(received_at: datetime, contribution_id: int) -> str:
    """Encodes received_at (ISO format) and contribution_id into an opaque Base64 string."""
    payload = f"{received_at.isoformat()}|{contribution_id}"
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("utf-8")


def decode_support_cursor(cursor_str: str) -> Tuple[datetime, int]:
    """
    Decodes an opaque Base64 cursor string into (received_at, contribution_id).
    Raises ValueError if malformed.
    """
    try:
        raw = base64.urlsafe_b64decode(cursor_str.encode("utf-8")).decode("utf-8")
        parts = raw.split("|")
        if len(parts) != 2:
            raise ValueError("Invalid cursor format")
        received_at = datetime.fromisoformat(parts[0])
        contribution_id = int(parts[1])
        return received_at, contribution_id
    except Exception as e:
        raise ValueError("Invalid cursor") from e


async def get_supporter_leaderboard(
    session: AsyncSession,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """
    Aggregate public contributions by supporter (Top 10).
    Ordered by:
    1. total_amount_vnd DESC
    2. last_supported_at ASC
    3. supporter_id ASC
    Excludes private contributions and non-active users.
    Single query with join, zero N+1.
    """
    safe_limit = min(max(1, limit), 10)
    stmt = (
        select(
            User.user_id,
            User.full_name,
            User.avatar_url,
            func.sum(SupportContribution.amount_vnd).label("total_amount_vnd"),
            func.count(SupportContribution.contribution_id).label("contribution_count"),
            func.max(SupportContribution.received_at).label("last_supported_at"),
        )
        .join(User, SupportContribution.supporter_id == User.user_id)
        .where(
            SupportContribution.is_public == True,  # noqa: E712
            User.status.in_([UserStatus.ACTIVE, "ACTIVE"]),
        )
        .group_by(User.user_id, User.full_name, User.avatar_url)
        .order_by(
            desc("total_amount_vnd"),
            asc("last_supported_at"),
            asc(User.user_id),
        )
        .limit(safe_limit)
    )
    res = await session.execute(stmt)
    rows = res.all()
    items = []
    for idx, row in enumerate(rows, start=1):
        items.append({
            "rank": idx,
            "supporter": {
                "user_id": row.user_id,
                "full_name": row.full_name,
                "avatar_url": row.avatar_url,
                "profile_path": f"/users/{row.user_id}",
            },
            "total_amount_vnd": int(row.total_amount_vnd),
            "contribution_count": int(row.contribution_count),
            "last_supported_at": row.last_supported_at,
        })
    return items


async def create_support_contribution(
    session: AsyncSession,
    supporter_id: int,
    amount_vnd: int,
    received_at: datetime,
    is_public: bool,
    recorded_by: int,
    transaction_ref: Optional[str] = None,
    admin_note: Optional[str] = None,
) -> SupportContribution:
    contribution = SupportContribution(
        supporter_id=supporter_id,
        amount_vnd=amount_vnd,
        received_at=received_at,
        is_public=is_public,
        recorded_by=recorded_by,
        transaction_ref=transaction_ref,
        admin_note=admin_note,
    )
    session.add(contribution)
    await session.flush()
    loaded = await get_support_contribution_by_id(session, contribution.contribution_id)
    assert loaded is not None
    return loaded


async def get_support_contribution_by_id(
    session: AsyncSession,
    contribution_id: int,
) -> Optional[SupportContribution]:
    stmt = (
        select(SupportContribution)
        .where(SupportContribution.contribution_id == contribution_id)
        .options(
            selectinload(SupportContribution.supporter),
            selectinload(SupportContribution.recorder),
        )
    )
    res = await session.execute(stmt)
    return res.scalar_one_or_none()


async def update_support_contribution_visibility(
    session: AsyncSession,
    contribution: SupportContribution,
    is_public: bool,
) -> SupportContribution:
    contribution.is_public = is_public
    await session.flush()
    return contribution


async def delete_support_contribution(
    session: AsyncSession,
    contribution: SupportContribution,
) -> None:
    await session.delete(contribution)
    await session.flush()


async def list_admin_support_contributions(
    session: AsyncSession,
    limit: int = 20,
    cursor: Optional[str] = None,
) -> Tuple[List[SupportContribution], Optional[str], bool]:
    safe_limit = min(max(1, limit), 50)
    stmt = (
        select(SupportContribution)
        .options(
            selectinload(SupportContribution.supporter),
            selectinload(SupportContribution.recorder),
        )
        .order_by(
            desc(SupportContribution.received_at),
            desc(SupportContribution.contribution_id),
        )
    )

    if cursor:
        cursor_received_at, cursor_id = decode_support_cursor(cursor)
        stmt = stmt.where(
            or_(
                SupportContribution.received_at < cursor_received_at,
                and_(
                    SupportContribution.received_at == cursor_received_at,
                    SupportContribution.contribution_id < cursor_id,
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
        next_cursor = encode_support_cursor(last_item.received_at, last_item.contribution_id)

    return items, next_cursor, has_more

async def search_supporters_for_admin(
    session: AsyncSession,
    query: str,
    limit: int = 10,
) -> List[User]:
    """
    Tìm kiếm người dùng cho Quản trị viên phục vụ ghi nhận ủng hộ thủ công.
    Hỗ trợ tìm theo tên hoặc User ID (nếu nhập số).
    Chỉ trả về người dùng ACTIVE, giới hạn an toàn tối đa 20.
    """
    trimmed = query.strip()
    if not trimmed:
        return []
    safe_limit = min(max(1, limit), 20)
    stmt = select(User).where(User.status == UserStatus.ACTIVE)
    if trimmed.isdigit():
        stmt = stmt.where(or_(User.user_id == int(trimmed), User.full_name.ilike(f"%{trimmed}%")))
    else:
        stmt = stmt.where(User.full_name.ilike(f"%{trimmed}%"))
    stmt = stmt.order_by(User.full_name.asc(), User.user_id.asc()).limit(safe_limit)
    res = await session.execute(stmt)
    return list(res.scalars().all())


# ======================================================================
# SUPPORT CLAIMS REPOSITORY
# ======================================================================

async def create_support_claim(
    session: AsyncSession,
    supporter_id: int,
    claimed_amount_vnd: int,
    claimed_transferred_at: datetime,
    sender_account_name: Optional[str] = None,
    wants_public: bool = False,
) -> SupportClaim:
    claim = SupportClaim(
        supporter_id=supporter_id,
        claimed_amount_vnd=claimed_amount_vnd,
        claimed_transferred_at=claimed_transferred_at,
        sender_account_name=sender_account_name,
        wants_public=wants_public,
        status=SupportClaimStatus.PENDING,
    )
    session.add(claim)
    await session.flush()
    return claim


async def get_support_claim_by_id(
    session: AsyncSession,
    claim_id: int,
    eager_load: bool = True,
    for_update: bool = False,
) -> Optional[SupportClaim]:
    stmt = select(SupportClaim).where(SupportClaim.claim_id == claim_id)
    if eager_load:
        stmt = stmt.options(
            selectinload(SupportClaim.supporter),
            selectinload(SupportClaim.reviewer),
            selectinload(SupportClaim.contribution),
        )
    if for_update:
        stmt = stmt.with_for_update()
    res = await session.execute(stmt)
    return res.scalar_one_or_none()


async def list_support_claims_by_user(
    session: AsyncSession,
    supporter_id: int,
    limit: int = 10,
) -> List[SupportClaim]:
    stmt = (
        select(SupportClaim)
        .where(SupportClaim.supporter_id == supporter_id)
        .order_by(
            desc(SupportClaim.created_at),
            desc(SupportClaim.claim_id),
        )
        .limit(min(max(1, limit), 50))
    )
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def list_admin_support_claims(
    session: AsyncSession,
    status: Optional[str] = None,
    limit: int = 20,
    cursor: Optional[str] = None,
) -> Tuple[List[SupportClaim], Optional[str], bool]:
    safe_limit = min(max(1, limit), 50)
    stmt = (
        select(SupportClaim)
        .options(
            selectinload(SupportClaim.supporter),
            selectinload(SupportClaim.reviewer),
            selectinload(SupportClaim.contribution),
        )
        .order_by(
            desc(SupportClaim.created_at),
            desc(SupportClaim.claim_id),
        )
    )
    if status:
        stmt = stmt.where(SupportClaim.status == status)

    if cursor:
        cursor_created_at, cursor_id = decode_support_cursor(cursor)
        stmt = stmt.where(
            or_(
                SupportClaim.created_at < cursor_created_at,
                and_(
                    SupportClaim.created_at == cursor_created_at,
                    SupportClaim.claim_id < cursor_id,
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
        next_cursor = encode_support_cursor(last_item.created_at, last_item.claim_id)

    return items, next_cursor, has_more
