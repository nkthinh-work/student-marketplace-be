from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.favorites.repository import FavoriteRepository
from app.modules.favorites.schemas import (
    FavoriteProductResponse,
    FavoriteListResponse,
    FavoriteIdsResponse,
)
from app.modules.products.repository import ProductRepository
from app.modules.users.models import User
from app.integrations.cloudinary import get_thumbnail_url


class FavoriteService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.favorite_repo = FavoriteRepository(db)
        self.product_repo = ProductRepository(db)

    async def add_favorite(self, user: User, product_id: int) -> None:
        """
        Favorite product nếu product đang AVAILABLE và chưa soft-delete.
        Idempotent — favorite lần 2 cũng OK.
        """
        product = await self.product_repo.get_by_id(product_id, include_deleted=False)

        # Product không tồn tại hoặc soft-deleted → 404
        if product is None:
            raise ProductNotFoundError()

        # HIDDEN, SOLD_OUT → 404
        if product.status != "AVAILABLE":
            raise ProductNotFoundError()

        await self.favorite_repo.upsert(user.user_id, product_id)

    async def remove_favorite(self, user: User, product_id: int) -> None:
        """
        Xóa favorite. Idempotent — unfavorite khi chưa favorite cũng OK.
        Không yêu cầu product phải còn AVAILABLE.
        """
        await self.favorite_repo.remove(user.user_id, product_id)

    async def list_favorites(
        self,
        user: User,
        limit: int = 20,
        cursor: Optional[str] = None,
    ) -> FavoriteListResponse:
        items, has_more, next_cursor = await self.favorite_repo.list_favorites(
            user_id=user.user_id,
            limit=limit,
            cursor=cursor,
        )

        response_items = []
        for product, favorited_at in items:
            thumbnail_url = None
            if product.images:
                for img in product.images:
                    if img.is_thumbnail:
                        thumbnail_url = get_thumbnail_url(img.image_url)
                        break
                if thumbnail_url is None and product.images:
                    thumbnail_url = get_thumbnail_url(product.images[0].image_url)

            response_items.append(
                FavoriteProductResponse(
                    product_id=product.product_id,
                    title=product.title,
                    price=product.price,
                    listing_type=product.listing_type,
                    status=product.status,
                    available_stock=product.available_stock,
                    thumbnail_url=thumbnail_url,
                    category=product.category,
                    seller=product.seller,
                    created_at=product.created_at,
                    favorited_at=favorited_at,
                )
            )

        return FavoriteListResponse(
            items=response_items,
            next_cursor=next_cursor,
            has_more=has_more,
        )

    async def get_favorite_ids(self, user: User) -> FavoriteIdsResponse:
        product_ids = await self.favorite_repo.get_visible_favorite_ids(user.user_id)
        return FavoriteIdsResponse(product_ids=product_ids)


class ProductNotFoundError(Exception):
    pass
