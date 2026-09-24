import base64
from datetime import datetime
from typing import Optional

from sqlalchemy import and_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.community_moments.models import (
    CommunityMoment,
    CommunityMomentStatus,
)

COMMUNITY_HERO_LOCK_NAMESPACE = "community_hero_lifecycle"


async def acquire_community_hero_lock(db: AsyncSession) -> None:
    """
    Acquires a PostgreSQL transaction-level advisory lock to serialize
    global Community Hero mutations (approval pruning, admin deletion).
    The lock is released automatically when the transaction completes (commit or rollback).
    """
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:lock_name))"),
        {"lock_name": COMMUNITY_HERO_LOCK_NAMESPACE},
    )


def encode_cursor(created_at: datetime, moment_id: int) -> str:
    """Encodes created_at (ISO format) and moment_id into an opaque Base64 string."""
    payload = f"{created_at.isoformat()}|{moment_id}"
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("utf-8")


def decode_cursor(cursor_str: str) -> tuple[datetime, int]:
    """
    Decodes an opaque Base64 cursor string into (created_at, moment_id).
    Raises ValueError if malformed.
    """
    try:
        raw = base64.urlsafe_b64decode(cursor_str.encode("utf-8")).decode("utf-8")
        parts = raw.split("|")
        if len(parts) != 2:
            raise ValueError("Invalid cursor format")
        created_at = datetime.fromisoformat(parts[0])
        moment_id = int(parts[1])
        return created_at, moment_id
    except Exception as e:
        raise ValueError("Invalid cursor") from e


class CommunityMomentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, moment: CommunityMoment) -> CommunityMoment:
        self.db.add(moment)
        await self.db.flush()
        return moment

    async def get_by_id(
        self,
        moment_id: int,
        for_update: bool = False,
        eager_load: bool = True,
    ) -> Optional[CommunityMoment]:
        stmt = select(CommunityMoment).where(CommunityMoment.moment_id == moment_id)
        if eager_load:
            stmt = stmt.options(
                selectinload(CommunityMoment.uploader),
                selectinload(CommunityMoment.reviewer),
            )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_pending_by_user(self, uploader_id: int) -> Optional[CommunityMoment]:
        stmt = (
            select(CommunityMoment)
            .where(
                CommunityMoment.uploader_id == uploader_id,
                CommunityMoment.status == CommunityMomentStatus.PENDING.value,
            )
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def delete(self, moment: CommunityMoment) -> None:
        await self.db.delete(moment)
        await self.db.flush()

    async def get_latest_approved(self, limit: int = 5) -> list[CommunityMoment]:
        stmt = (
            select(CommunityMoment)
            .where(CommunityMoment.status == CommunityMomentStatus.APPROVED.value)
            .order_by(
                CommunityMoment.reviewed_at.desc(),
                CommunityMoment.moment_id.desc(),
            )
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_all_approved(self, for_update: bool = False) -> list[CommunityMoment]:
        stmt = (
            select(CommunityMoment)
            .where(CommunityMoment.status == CommunityMomentStatus.APPROVED.value)
            .order_by(
                CommunityMoment.reviewed_at.desc(),
                CommunityMoment.moment_id.desc(),
            )
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_admin_moments_cursor(
        self,
        status: Optional[str] = None,
        cursor: Optional[tuple[datetime, int]] = None,
        limit: int = 20,
    ) -> tuple[list[CommunityMoment], bool, Optional[tuple[datetime, int]]]:
        stmt = (
            select(CommunityMoment)
            .options(
                selectinload(CommunityMoment.uploader),
                selectinload(CommunityMoment.reviewer),
            )
            .order_by(
                CommunityMoment.created_at.desc(),
                CommunityMoment.moment_id.desc(),
            )
        )

        conditions = []
        if status:
            conditions.append(CommunityMoment.status == status)

        if cursor:
            cursor_dt, cursor_id = cursor
            conditions.append(
                or_(
                    CommunityMoment.created_at < cursor_dt,
                    and_(
                        CommunityMoment.created_at == cursor_dt,
                        CommunityMoment.moment_id < cursor_id,
                    ),
                )
            )

        if conditions:
            stmt = stmt.where(and_(*conditions))

        stmt = stmt.limit(limit + 1)
        result = await self.db.execute(stmt)
        rows = list(result.scalars().all())

        has_more = len(rows) > limit
        items = rows[:limit] if has_more else rows

        next_cursor = None
        if has_more and items:
            last = items[-1]
            next_cursor = (last.created_at, last.moment_id)

        return items, has_more, next_cursor
