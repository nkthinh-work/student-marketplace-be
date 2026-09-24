from datetime import timedelta
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.daily_needs.models import DailyNeed
from app.modules.daily_needs.schemas import (
    DailyNeedResponse,
    DailyNeedAuthor,
    DailyNeedListResponse,
    DailyNeedCreateOrUpdate,
    DailyNeedPublicResponse,
    DailyNeedSummaryResponse,
)
from app.modules.daily_needs.repository import (
    DailyNeedRepository,
    get_vietnam_today,
)
from app.modules.users.models import User



class DailyNeedService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = DailyNeedRepository(db)

    def _to_response(
        self, item: DailyNeed, checkin_created: bool = False
    ) -> DailyNeedResponse:
        author = DailyNeedAuthor(
            user_id=item.user.user_id,
            full_name=item.user.full_name,
            avatar_url=item.user.avatar_url,
        )
        return DailyNeedResponse(
            daily_need_id=item.daily_need_id,
            content=item.content,
            note_date=item.note_date,
            created_at=item.created_at,
            updated_at=item.updated_at,
            author=author,
            checkin_created=checkin_created,
        )

    async def get_today_public_notes(self, limit: int = 10) -> DailyNeedListResponse:
        today = get_vietnam_today()
        notes = await self.repo.get_today_notes(today, limit=min(limit, 10))
        return DailyNeedListResponse(
            items=[self._to_response(note) for note in notes]
        )

    async def get_my_today_note(
        self, current_user: User
    ) -> Optional[DailyNeedResponse]:
        today = get_vietnam_today()
        note = await self.repo.get_user_note_for_date(current_user.user_id, today)
        if not note:
            return None
        return self._to_response(note)

    async def upsert_my_today_note(
        self, current_user: User, payload: DailyNeedCreateOrUpdate
    ) -> DailyNeedResponse:
        today = get_vietnam_today()
        # 1. Upsert today's daily_needs row
        note = await self.repo.upsert_user_note(
            user_id=current_user.user_id,
            note_date=today,
            content=payload.content,
        )
        # 2. Atomically insert check-in in the same transaction
        checkin_created = await self.repo.record_checkin(
            user_id=current_user.user_id,
            checkin_date=today,
        )
        # 3. Commit both operations together
        await self.db.commit()
        return self._to_response(note, checkin_created=checkin_created)

    async def delete_my_today_note(self, current_user: User) -> bool:
        today = get_vietnam_today()
        deleted = await self.repo.delete_user_note_for_date(
            current_user.user_id, today
        )
        if deleted:
            await self.db.commit()
        return deleted

    async def get_my_summary(
        self, current_user: User
    ) -> DailyNeedSummaryResponse:
        today = get_vietnam_today()
        today_note = await self.repo.get_user_note_for_date(
            current_user.user_id, today
        )
        has_journal_today = today_note is not None
        has_checked_in_today = await self.repo.has_user_checked_in(
            current_user.user_id, today
        )

        if has_checked_in_today:
            streak_count = await self.repo.calculate_user_streak(
                current_user.user_id, today
            )
        else:
            yesterday = today - timedelta(days=1)
            has_checked_in_yesterday = await self.repo.has_user_checked_in(
                current_user.user_id, yesterday
            )
            if has_checked_in_yesterday:
                streak_count = await self.repo.calculate_user_streak(
                    current_user.user_id, yesterday
                )
            else:
                streak_count = 0

        return DailyNeedSummaryResponse(
            today_journal=self._to_response(today_note) if today_note else None,
            has_journal_today=has_journal_today,
            has_checked_in_today=has_checked_in_today,
            has_posted_today=has_checked_in_today,  # Deprecated: equals has_checked_in_today for backwards compatibility
            streak_count=streak_count,
        )


    async def get_user_today_public_note(
        self, user_id: int
    ) -> Optional[DailyNeedPublicResponse]:
        today = get_vietnam_today()
        note = await self.repo.get_user_note_for_date(user_id, today)
        if not note:
            return None
        author = DailyNeedAuthor(
            user_id=note.user.user_id,
            full_name=note.user.full_name,
            avatar_url=note.user.avatar_url,
        )
        return DailyNeedPublicResponse(
            daily_need_id=note.daily_need_id,
            content=note.content,
            note_date=note.note_date,
            updated_at=note.updated_at,
            author=author,
        )

