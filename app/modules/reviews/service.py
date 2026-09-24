import logging
from datetime import datetime
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.privacy import anonymize_name
from app.modules.notifications.models import NotificationType
from app.modules.notifications.repository import NotificationRepository
from app.modules.notifications.schemas import NotificationResponse
from app.modules.orders.models import Order, OrderStatus
from app.modules.orders.websocket import publish_user_event
from app.modules.reviews.models import Review
from app.modules.reviews.repository import (
    ReviewRepository,
    decode_review_cursor,
    encode_review_cursor,
)
from app.modules.reviews.schemas import (
    OrderReviewResponse,
    PublicSellerReviewItem,
    PublicSellerReviewsCursorPage,
    ReviewCreateRequest,
    ReviewUpdateRequest,
)
from app.modules.users.models import User, UserStatus

logger = logging.getLogger("app.reviews")


async def safe_publish_user_notification(user_id: int, notif_dto: NotificationResponse) -> None:
    """Best-effort post-commit realtime notification dispatch isolated per recipient."""
    try:
        await publish_user_event(
            user_id,
            {
                "type": "NOTIFICATION_CREATED",
                "notification": notif_dto.model_dump(mode="json"),
            },
        )
    except Exception as err:
        logger.warning(f"Failed to publish NOTIFICATION_CREATED to user {user_id}: {err}")



class ReviewService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.review_repo = ReviewRepository(db)

    async def _get_order_for_participant(
        self, order_id: int, user_id: int
    ) -> Order:
        stmt = select(Order).where(Order.order_id == order_id)
        result = await self.db.execute(stmt)
        order = result.scalar_one_or_none()
        if not order or (order.buyer_id != user_id and order.seller_id != user_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Không tìm thấy đơn hàng.",
            )
        return order

    async def create_order_review(
        self, order_id: int, user: User, payload: ReviewCreateRequest
    ) -> OrderReviewResponse:
        order = await self._get_order_for_participant(order_id, user.user_id)

        # Only the buyer can review the seller
        if order.seller_id == user.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Chỉ người mua mới có thể đánh giá người bán.",
            )

        # Order must be COMPLETED
        if order.status != OrderStatus.COMPLETED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Chỉ có thể đánh giá sau khi đơn hàng hoàn tất.",
            )

        if order.buyer_id == order.seller_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Người bán không thể tự đánh giá chính mình.",
            )

        # Check existing review for this order and buyer
        existing = await self.review_repo.get_by_order_and_reviewer(
            order_id, user.user_id
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Bạn đã đánh giá đơn hàng này.",
            )

        review = Review(
            order_id=order_id,
            reviewer_id=user.user_id,
            reviewee_id=order.seller_id,
            rating=payload.rating,
            comment=payload.comment,
        )

        try:
            await self.review_repo.create(review)

            notification_repo = NotificationRepository(self.db)
            notif = await notification_repo.create(
                user_id=review.reviewee_id,
                type=NotificationType.NEW_REVIEW.value,
                title="Bạn có đánh giá mới",
                body=f"Đơn {order.order_code} vừa nhận được đánh giá {review.rating} sao.",
                ref_type="ORDER",
                ref_id=order_id,
            )

            # Flush session to guarantee generated IDs and column defaults are populated
            await self.db.flush()

            # Pre-commit immutable snapshots (protects against ORM session expiration after commit)
            reviewee_id = review.reviewee_id
            notif_snapshot = NotificationResponse.model_validate(notif)
            response_snapshot = OrderReviewResponse(
                review_id=review.review_id,
                order_id=review.order_id,
                reviewer_id=review.reviewer_id,
                reviewee_id=review.reviewee_id,
                rating=review.rating,
                comment=review.comment,
                reviewer_name=user.full_name,
                created_at=review.created_at,
                updated_at=review.updated_at,
            )

            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            if "ux_reviews_order_reviewer" in str(exc):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Bạn đã đánh giá đơn hàng này.",
                )
            raise
        except Exception:
            await self.db.rollback()
            raise

        # Post-commit best-effort realtime dispatch using plain snapshot values only
        await safe_publish_user_notification(reviewee_id, notif_snapshot)

        return response_snapshot

    async def update_order_review(
        self, order_id: int, user: User, payload: ReviewUpdateRequest
    ) -> OrderReviewResponse:
        if not payload.model_fields_set:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Phải cung cấp ít nhất một trường để cập nhật (rating hoặc comment).",
            )

        review = await self.review_repo.get_by_order_and_reviewer(
            order_id, user.user_id, for_update=True
        )
        if not review or review.reviewer_id != user.user_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Không tìm thấy đánh giá cho đơn hàng này.",
            )

        if "rating" in payload.model_fields_set:
            if payload.rating is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Số sao đánh giá không được để trống.",
                )
            review.rating = payload.rating

        if "comment" in payload.model_fields_set:
            review.comment = payload.comment

        await self.db.commit()
        await self.db.refresh(review)

        reviewer_name = user.full_name
        return OrderReviewResponse(
            review_id=review.review_id,
            order_id=review.order_id,
            reviewer_id=review.reviewer_id,
            reviewee_id=review.reviewee_id,
            rating=review.rating,
            comment=review.comment,
            reviewer_name=reviewer_name,
            created_at=review.created_at,
            updated_at=review.updated_at,
        )

    async def get_order_review(
        self, order_id: int, user: User
    ) -> Optional[OrderReviewResponse]:
        order = await self._get_order_for_participant(order_id, user.user_id)
        review = await self.review_repo.get_by_order_id(order_id)
        if not review:
            return None

        reviewer_name = (
            review.reviewer.full_name if review.reviewer else "Người mua"
        )
        return OrderReviewResponse(
            review_id=review.review_id,
            order_id=review.order_id,
            reviewer_id=review.reviewer_id,
            reviewee_id=review.reviewee_id,
            rating=review.rating,
            comment=review.comment,
            reviewer_name=reviewer_name,
            created_at=review.created_at,
            updated_at=review.updated_at,
        )

    async def get_public_seller_reviews(
        self, seller_id: int, limit: int = 10, cursor: Optional[str] = None
    ) -> PublicSellerReviewsCursorPage:
        # Validate seller exists and is ACTIVE
        stmt = select(User).where(User.user_id == seller_id)
        result = await self.db.execute(stmt)
        seller = result.scalar_one_or_none()
        if not seller or seller.status != UserStatus.ACTIVE:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Không tìm thấy người dùng.",
            )

        cursor_dt = None
        cursor_id = None
        if cursor:
            cursor_dt, cursor_id = decode_review_cursor(cursor)

        reviews = await self.review_repo.get_seller_reviews_cursor(
            seller_id=seller_id,
            limit=limit,
            cursor_dt=cursor_dt,
            cursor_id=cursor_id,
        )

        has_more = len(reviews) > limit
        page_items = reviews[:limit]

        next_cursor = None
        if has_more and page_items:
            last_item = page_items[-1]
            next_cursor = encode_review_cursor(
                last_item.created_at, last_item.review_id
            )

        items = [
            PublicSellerReviewItem(
                rating=r.rating,
                comment=r.comment,
                verified_transaction=True,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
            for r in page_items
        ]

        return PublicSellerReviewsCursorPage(
            items=items,
            next_cursor=next_cursor,
            has_more=has_more,
        )
