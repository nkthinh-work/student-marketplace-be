from typing import Optional, Sequence
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.categories.models import Category


class CategoryRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_active(self) -> Sequence[Category]:
        stmt = (
            select(Category)
            .where(Category.is_deleted.is_(False))
            .order_by(Category.category_id.asc())
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_by_id(self, category_id: int) -> Optional[Category]:
        stmt = select(Category).where(
            Category.category_id == category_id,
            Category.is_deleted.is_(False),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> Optional[Category]:
        stmt = select(Category).where(
            Category.slug == slug,
            Category.is_deleted.is_(False),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
