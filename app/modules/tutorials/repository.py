from typing import Optional, Sequence
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tutorials.models import Tutorial


class TutorialRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_published_tutorials(self) -> Sequence[Tutorial]:
        """Lấy tất cả các video hướng dẫn đã xuất bản, sắp xếp theo sort_order và tutorial_id."""
        stmt = (
            select(Tutorial)
            .where(Tutorial.is_published.is_(True))
            .order_by(Tutorial.sort_order.asc(), Tutorial.tutorial_id.asc())
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_all_tutorials(
        self, feature_key: Optional[str] = None
    ) -> Sequence[Tutorial]:
        """Lấy tất cả các video hướng dẫn (kể cả bản nháp) phục vụ quản trị."""
        stmt = select(Tutorial)
        if feature_key:
            stmt = stmt.where(Tutorial.feature_key == feature_key)
        stmt = stmt.order_by(
            Tutorial.feature_key.asc(),
            Tutorial.sort_order.asc(),
            Tutorial.tutorial_id.asc(),
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_by_id(
        self, tutorial_id: int, for_update: bool = False
    ) -> Optional[Tutorial]:
        """Lấy một tutorial theo ID, hỗ trợ row lock nếu cần."""
        stmt = select(Tutorial).where(Tutorial.tutorial_id == tutorial_id)
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def get_by_ids(
        self, tutorial_ids: list[int], for_update: bool = False
    ) -> Sequence[Tutorial]:
        """Lấy danh sách tutorials theo danh sách ID."""
        if not tutorial_ids:
            return []
        stmt = select(Tutorial).where(Tutorial.tutorial_id.in_(tutorial_ids))
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_max_sort_order(self, feature_key: str) -> int:
        """Lấy giá trị sort_order lớn nhất hiện tại của một feature_key."""
        stmt = select(func.coalesce(func.max(Tutorial.sort_order), 0)).where(
            Tutorial.feature_key == feature_key
        )
        result = await self.db.execute(stmt)
        return result.scalar() or 0

    async def create(self, tutorial: Tutorial) -> Tutorial:
        self.db.add(tutorial)
        await self.db.flush()
        return tutorial

    async def delete(self, tutorial: Tutorial) -> None:
        await self.db.delete(tutorial)
        await self.db.flush()
