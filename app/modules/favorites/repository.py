import base64
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, delete, and_, or_, exists
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.modules.favorites.models import Favorite
from app.modules.products.models import Product
from app.modules.users.capability_models import UserCapabilityRestriction, CapabilityType


def _encode_cursor(created_at: datetime, product_id: int) -> str:
    payload = f"{created_at.isoformat()}|{product_id}"
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("utf-8")


def _decode_cursor(cursor_str: str) -> tuple[datetime, int]:
    try:
        raw = base64.urlsafe_b64decode(cursor_str.encode("utf-8")).decode("utf-8")
        parts = raw.split("|")
        if len(parts) != 2:
            raise ValueError("Invalid cursor format")
        return datetime.fromisoformat(parts[0]), int(parts[1])
    except Exception as e:
        raise ValueError("Invalid cursor") from e


# Điều kiện product hiển thị cho Favorites (loại trừ cả seller bị hạn chế bán hàng)
def _get_visible_product_condition(now_utc: Optional[datetime] = None):
    if now_utc is None:
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    sell_restricted_exists = exists(
        select(1)
        .select_from(UserCapabilityRestriction)
        .where(
            UserCapabilityRestriction.user_id == Product.seller_id,
            UserCapabilityRestriction.capability == CapabilityType.SELL.value,
            UserCapabilityRestriction.revoked_at.is_(None),
            UserCapabilityRestriction.starts_at <= now_utc,
            or_(
                UserCapabilityRestriction.expires_at.is_(None),
                UserCapabilityRestriction.expires_at > now_utc,
            ),
        )
    )
    return and_(
        Product.is_deleted.is_(False),
        Product.status == "AVAILABLE",
        Product.moderation_status == "CLEAR",
        ~sell_restricted_exists,
    )


class FavoriteRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def upsert(self, user_id: int, product_id: int) -> None:
        """Idempotent INSERT — ON CONFLICT DO NOTHING."""
        stmt = (
            pg_insert(Favorite)
            .values(user_id=user_id, product_id=product_id)
            .on_conflict_do_nothing(index_elements=["user_id", "product_id"])
        )
        await self.db.execute(stmt)
        await self.db.flush()

    async def remove(self, user_id: int, product_id: int) -> None:
        """Idempotent DELETE — rowcount=0 là OK."""
        stmt = delete(Favorite).where(
            Favorite.user_id == user_id,
            Favorite.product_id == product_id,
        )
        await self.db.execute(stmt)
        await self.db.flush()

    async def list_favorites(
        self,
        user_id: int,
        limit: int = 20,
        cursor: Optional[str] = None,
    ) -> tuple[list[tuple[Product, datetime]], bool, Optional[str]]:
        """
        Trả danh sách (Product, favorited_at) cho user,
        chỉ gồm product AVAILABLE + chưa soft-delete.
        """
        stmt = (
            select(Product, Favorite.created_at.label("favorited_at"))
            .join(Favorite, Favorite.product_id == Product.product_id)
            .where(
                Favorite.user_id == user_id,
                _get_visible_product_condition(),
            )
        )

        if cursor:
            cursor_time, cursor_pid = _decode_cursor(cursor)
            stmt = stmt.where(
                (Favorite.created_at < cursor_time)
                | (
                    and_(
                        Favorite.created_at == cursor_time,
                        Favorite.product_id < cursor_pid,
                    )
                )
            )

        stmt = stmt.order_by(
            Favorite.created_at.desc(),
            Favorite.product_id.desc(),
        ).limit(limit + 1)

        result = await self.db.execute(stmt)
        rows = result.all()

        has_more = len(rows) > limit
        if has_more:
            rows = rows[:limit]

        items = [(row[0], row[1]) for row in rows]

        next_cursor = None
        if has_more and items:
            last_product, last_fav_at = items[-1]
            next_cursor = _encode_cursor(last_fav_at, last_product.product_id)

        return items, has_more, next_cursor

    async def get_visible_favorite_ids(self, user_id: int) -> list[int]:
        """Trả list product_id đang AVAILABLE cho user — dùng cho Set membership."""
        stmt = (
            select(Favorite.product_id)
            .join(Product, Favorite.product_id == Product.product_id)
            .where(
                Favorite.user_id == user_id,
                _get_visible_product_condition(),
            )
            .order_by(Favorite.product_id)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
