import base64
from datetime import datetime
import json
from typing import Optional

from sqlalchemy import func, select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.modules.reviews.models import Review


def encode_review_cursor(created_at: datetime, review_id: int) -> str:
    data = {
        "created_at": created_at.isoformat(),
        "review_id": review_id,
    }
    raw = json.dumps(data)
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")


def decode_review_cursor(cursor: str) -> tuple[datetime, int]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("utf-8")).decode("utf-8")
        data = json.loads(raw)
        return (
            datetime.fromisoformat(data["created_at"]),
            int(data["review_id"]),
        )
    except Exception as e:
        raise ValueError("Định dạng con trỏ phân trang không hợp lệ.") from e


class ReviewRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, review: Review) -> Review:
        self.db.add(review)
        await self.db.flush()
        return review

    async def get_by_id(
        self, review_id: int, for_update: bool = False
    ) -> Optional[Review]:
        stmt = select(Review).where(Review.review_id == review_id)
        if for_update:
            stmt = stmt.with_for_update(of=Review)
        else:
            stmt = stmt.options(joinedload(Review.reviewer))
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_order_and_reviewer(
        self, order_id: int, reviewer_id: int, for_update: bool = False
    ) -> Optional[Review]:
        stmt = select(Review).where(
            Review.order_id == order_id,
            Review.reviewer_id == reviewer_id,
        )
        if for_update:
            stmt = stmt.with_for_update(of=Review)
        else:
            stmt = stmt.options(joinedload(Review.reviewer))
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_order_id(self, order_id: int) -> Optional[Review]:
        stmt = (
            select(Review)
            .where(Review.order_id == order_id)
            .options(joinedload(Review.reviewer))
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_seller_rating_summary(
        self, seller_id: int
    ) -> tuple[Optional[float], int]:
        stmt = select(
            func.avg(Review.rating),
            func.count(Review.review_id),
        ).where(Review.reviewee_id == seller_id)
        result = await self.db.execute(stmt)
        avg_val, cnt_val = result.one()
        avg_rating = round(float(avg_val), 1) if avg_val is not None else None
        review_count = int(cnt_val) if cnt_val is not None else 0
        return avg_rating, review_count

    async def get_seller_reviews_cursor(
        self,
        seller_id: int,
        limit: int = 10,
        cursor_dt: Optional[datetime] = None,
        cursor_id: Optional[int] = None,
    ) -> list[Review]:
        stmt = (
            select(Review)
            .where(Review.reviewee_id == seller_id)
            .options(joinedload(Review.reviewer))
        )
        if cursor_dt is not None and cursor_id is not None:
            stmt = stmt.where(
                or_(
                    Review.created_at < cursor_dt,
                    and_(
                        Review.created_at == cursor_dt,
                        Review.review_id < cursor_id,
                    ),
                )
            )
        stmt = stmt.order_by(Review.created_at.desc(), Review.review_id.desc()).limit(
            limit + 1
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
