from datetime import datetime, date
from typing import Optional
from zoneinfo import ZoneInfo
from sqlalchemy import select, text
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.daily_needs.models import DailyNeed

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")



def get_vietnam_today() -> date:
    return datetime.now(VN_TZ).date()


def get_vietnam_now() -> datetime:
    return datetime.now(VN_TZ)


class DailyNeedRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_today_notes(self, today: date, limit: int = 10) -> list[DailyNeed]:
        stmt = (
            select(DailyNeed)
            .options(joinedload(DailyNeed.user))
            .where(DailyNeed.note_date == today)
            .order_by(DailyNeed.updated_at.desc(), DailyNeed.daily_need_id.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().unique().all())

    async def get_user_note_for_date(
        self, user_id: int, note_date: date
    ) -> Optional[DailyNeed]:
        stmt = (
            select(DailyNeed)
            .options(joinedload(DailyNeed.user))
            .where(DailyNeed.user_id == user_id, DailyNeed.note_date == note_date)
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def upsert_user_note(
        self, user_id: int, note_date: date, content: str
    ) -> DailyNeed:
        now = get_vietnam_now()
        sql = text("""
            INSERT INTO daily_needs (user_id, note_date, content, created_at, updated_at)
            VALUES (:user_id, :note_date, :content, :now, :now)
            ON CONFLICT (user_id, note_date)
            DO UPDATE SET content = EXCLUDED.content, updated_at = EXCLUDED.updated_at
            RETURNING daily_need_id;
        """)
        await self.db.execute(
            sql,
            {
                "user_id": user_id,
                "note_date": note_date,
                "content": content,
                "now": now,
            },
        )
        # Fetch with user eagerly joined
        return await self.get_user_note_for_date(user_id, note_date)


    async def delete_user_note_for_date(
        self, user_id: int, note_date: date
    ) -> bool:
        note = await self.get_user_note_for_date(user_id, note_date)
        if not note:
            return False
        await self.db.delete(note)
        await self.db.flush()
        return True

    async def record_checkin(self, user_id: int, checkin_date: date) -> bool:
        """
        Atomically and idempotently records an immutable daily check-in.
        Returns True if a new check-in row was inserted, False if one already existed.
        """
        sql = text("""
            INSERT INTO daily_journal_checkins (user_id, checkin_date, created_at)
            VALUES (:user_id, :checkin_date, NOW())
            ON CONFLICT (user_id, checkin_date) DO NOTHING
            RETURNING checkin_id;
        """)
        result = await self.db.execute(sql, {"user_id": user_id, "checkin_date": checkin_date})
        row = result.first()
        return row is not None

    async def has_user_checked_in(self, user_id: int, checkin_date: date) -> bool:
        """
        Checks whether the user has earned a check-in for the given calendar date.
        """
        sql = text("""
            SELECT 1 FROM daily_journal_checkins
            WHERE user_id = :user_id AND checkin_date = :checkin_date
            LIMIT 1;
        """)
        result = await self.db.execute(sql, {"user_id": user_id, "checkin_date": checkin_date})
        return result.scalar() is not None

    async def calculate_user_streak(self, user_id: int, anchor_date: date) -> int:
        """
        Calculates consecutive days ending at anchor_date using a recursive CTE on daily_journal_checkins.
        Stops automatically at the first missing day with zero arbitrary cap.
        Uses the unique index/constraint on (user_id, checkin_date).
        """
        sql = text("""
            WITH RECURSIVE streak_chain AS (
                SELECT checkin_date, 1 AS streak_len
                FROM daily_journal_checkins
                WHERE user_id = :user_id AND checkin_date = :anchor_date
                UNION ALL
                SELECT c.checkin_date, sc.streak_len + 1
                FROM daily_journal_checkins c
                JOIN streak_chain sc ON c.checkin_date = CAST(sc.checkin_date - INTERVAL '1 day' AS DATE)
                WHERE c.user_id = :user_id
            )
            SELECT COALESCE(MAX(streak_len), 0) FROM streak_chain;
        """)
        result = await self.db.execute(sql, {"user_id": user_id, "anchor_date": anchor_date})
        val = result.scalar()
        return int(val or 0)


