from typing import Sequence
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.categories.models import Category
from app.modules.categories.repository import CategoryRepository


class CategoryService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = CategoryRepository(db)

    async def list_active_categories(self) -> Sequence[Category]:
        return await self.repository.list_active()

    async def get_category_by_id(self, category_id: int) -> Category:
        category = await self.repository.get_by_id(category_id)
        if not category:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Category not found.",
            )
        return category
