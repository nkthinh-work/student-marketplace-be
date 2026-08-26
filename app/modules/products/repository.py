import base64
from datetime import datetime
from decimal import Decimal
from typing import Optional, Sequence
from sqlalchemy import (
    select,
    update,
    func,
    text,
    or_,
    and_,
)
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.products.models import Product, ProductImage


def encode_cursor(created_at: datetime, product_id: int) -> str:
    """Encodes created_at (ISO format) and product_id into an opaque Base64 string."""
    payload = f"{created_at.isoformat()}|{product_id}"
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("utf-8")


def decode_cursor(cursor_str: str) -> tuple[datetime, int]:
    """
    Decodes an opaque Base64 cursor string into (created_at, product_id).
    Raises ValueError if malformed.
    """
    try:
        raw = base64.urlsafe_b64decode(cursor_str.encode("utf-8")).decode("utf-8")
        parts = raw.split("|")
        if len(parts) != 2:
            raise ValueError("Invalid cursor format")
        created_at = datetime.fromisoformat(parts[0])
        product_id = int(parts[1])
        return created_at, product_id
    except Exception as e:
        raise ValueError("Invalid cursor") from e


class ProductRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, product: Product) -> Product:
        self.db.add(product)
        await self.db.flush()
        await self.db.refresh(product)
        return product

    async def get_by_id(
        self,
        product_id: int,
        include_deleted: bool = False,
    ) -> Optional[Product]:
        stmt = select(Product).where(Product.product_id == product_id)
        if not include_deleted:
            stmt = stmt.where(Product.is_deleted.is_(False))
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_public(
        self,
        category_id: Optional[int] = None,
        listing_type: Optional[str] = None,
        min_price: Optional[Decimal] = None,
        max_price: Optional[Decimal] = None,
        search_query: Optional[str] = None,
        limit: int = 20,
        cursor: Optional[tuple[datetime, int]] = None,
    ) -> tuple[list[Product], bool, Optional[tuple[datetime, int]]]:
        stmt = (
            select(Product)
            .where(
                Product.is_deleted.is_(False),
                Product.status == "AVAILABLE",
            )
        )

        if category_id is not None:
            stmt = stmt.where(Product.category_id == category_id)

        if listing_type is not None:
            stmt = stmt.where(Product.listing_type == listing_type)

        if min_price is not None:
            stmt = stmt.where(Product.price >= min_price)

        if max_price is not None:
            stmt = stmt.where(Product.price <= max_price)

        if search_query and search_query.strip():
            cleaned_query = search_query.strip()
            # Khớp biểu thức GIN full-text index trong PostgreSQL
            ts_vector = func.to_tsvector(
                "simple",
                func.coalesce(Product.title, "") + " " + func.coalesce(Product.description, ""),
            )
            stmt = stmt.where(
                ts_vector.op("@@")(func.plainto_tsquery("simple", cleaned_query))
            )

        if cursor is not None:
            cursor_time, cursor_id = cursor
            stmt = stmt.where(
                or_(
                    Product.created_at < cursor_time,
                    and_(
                        Product.created_at == cursor_time,
                        Product.product_id < cursor_id,
                    ),
                )
            )

        stmt = stmt.order_by(
            Product.created_at.desc(),
            Product.product_id.desc(),
        ).limit(limit + 1)

        result = await self.db.execute(stmt)
        items = list(result.scalars().all())

        has_more = len(items) > limit
        if has_more:
            items = items[:limit]
            next_cursor = (items[-1].created_at, items[-1].product_id)
        else:
            next_cursor = None

        return items, has_more, next_cursor

    async def list_by_seller(
        self,
        seller_id: int,
        status: Optional[str] = None,
        limit: int = 20,
        cursor: Optional[tuple[datetime, int]] = None,
    ) -> tuple[list[Product], bool, Optional[tuple[datetime, int]]]:
        stmt = select(Product).where(
            Product.seller_id == seller_id,
            Product.is_deleted.is_(False),
        )

        if status is not None:
            stmt = stmt.where(Product.status == status)

        if cursor is not None:
            cursor_time, cursor_id = cursor
            stmt = stmt.where(
                or_(
                    Product.created_at < cursor_time,
                    and_(
                        Product.created_at == cursor_time,
                        Product.product_id < cursor_id,
                    ),
                )
            )

        stmt = stmt.order_by(
            Product.created_at.desc(),
            Product.product_id.desc(),
        ).limit(limit + 1)

        result = await self.db.execute(stmt)
        items = list(result.scalars().all())

        has_more = len(items) > limit
        if has_more:
            items = items[:limit]
            next_cursor = (items[-1].created_at, items[-1].product_id)
        else:
            next_cursor = None

        return items, has_more, next_cursor

    async def update(self, product: Product) -> Product:
        await self.db.flush()
        await self.db.refresh(product)
        return product


class ProductImageRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, image_id: int) -> Optional[ProductImage]:
        stmt = select(ProductImage).where(ProductImage.image_id == image_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_product_and_id(
        self, product_id: int, image_id: int
    ) -> Optional[ProductImage]:
        stmt = select(ProductImage).where(
            ProductImage.product_id == product_id,
            ProductImage.image_id == image_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_product(self, product_id: int) -> Sequence[ProductImage]:
        stmt = (
            select(ProductImage)
            .where(ProductImage.product_id == product_id)
            .order_by(ProductImage.sort_order.asc(), ProductImage.image_id.asc())
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def count_by_product(self, product_id: int) -> int:
        stmt = (
            select(func.count())
            .select_from(ProductImage)
            .where(ProductImage.product_id == product_id)
        )
        result = await self.db.execute(stmt)
        return result.scalar() or 0

    async def get_max_sort_order(self, product_id: int) -> int:
        stmt = (
            select(func.max(ProductImage.sort_order))
            .where(ProductImage.product_id == product_id)
        )
        result = await self.db.execute(stmt)
        val = result.scalar()
        return val if val is not None else -1

    async def create(self, product_image: ProductImage) -> ProductImage:
        self.db.add(product_image)
        await self.db.flush()
        await self.db.refresh(product_image)
        return product_image

    async def delete(self, product_image: ProductImage) -> None:
        await self.db.delete(product_image)
        await self.db.flush()

    async def set_thumbnail(self, product_id: int, image_id: int) -> None:
        # Chuyển thumbnail atomic: bỏ active cũ rồi gán cho ảnh mới
        await self.db.execute(
            update(ProductImage)
            .where(
                ProductImage.product_id == product_id,
                ProductImage.is_thumbnail.is_(True),
            )
            .values(is_thumbnail=False)
        )
        await self.db.execute(
            update(ProductImage)
            .where(
                ProductImage.product_id == product_id,
                ProductImage.image_id == image_id,
            )
            .values(is_thumbnail=True)
        )
        await self.db.flush()

    async def reorder_images(
        self, product_id: int, reorder_items: list[tuple[int, int]]
    ) -> None:
        for img_id, order in reorder_items:
            await self.db.execute(
                update(ProductImage)
                .where(
                    ProductImage.product_id == product_id,
                    ProductImage.image_id == img_id,
                )
                .values(sort_order=order)
            )
        await self.db.flush()
