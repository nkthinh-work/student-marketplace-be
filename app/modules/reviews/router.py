from typing import Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_active_user
from app.modules.reviews.schemas import (
    OrderReviewResponse,
    PublicSellerReviewsCursorPage,
    ReviewCreateRequest,
    ReviewUpdateRequest,
)
from app.modules.reviews.service import ReviewService
from app.modules.users.models import User

router = APIRouter(tags=["Reviews"])


@router.post(
    "/orders/{order_id}/review",
    response_model=OrderReviewResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Đánh giá người bán sau khi hoàn tất đơn hàng",
)
async def create_order_review(
    order_id: int,
    payload: ReviewCreateRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> OrderReviewResponse:
    service = ReviewService(db)
    return await service.create_order_review(order_id, current_user, payload)


@router.get(
    "/orders/{order_id}/review",
    response_model=Optional[OrderReviewResponse],
    status_code=status.HTTP_200_OK,
    summary="Lấy thông tin đánh giá của đơn hàng (dành cho người mua và người bán)",
)
async def get_order_review(
    order_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Optional[OrderReviewResponse]:
    service = ReviewService(db)
    return await service.get_order_review(order_id, current_user)


@router.patch(
    "/orders/{order_id}/review",
    response_model=OrderReviewResponse,
    status_code=status.HTTP_200_OK,
    summary="Chỉnh sửa đánh giá của người mua",
)
async def update_order_review(
    order_id: int,
    payload: ReviewUpdateRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> OrderReviewResponse:
    service = ReviewService(db)
    return await service.update_order_review(order_id, current_user, payload)


@router.get(
    "/users/{user_id}/reviews",
    response_model=PublicSellerReviewsCursorPage,
    status_code=status.HTTP_200_OK,
    summary="Lấy danh sách đánh giá công khai của người bán (phân trang keyset)",
)
async def get_public_seller_reviews(
    user_id: int,
    limit: int = Query(10, ge=1, le=50, description="Số lượng đánh giá mỗi trang"),
    cursor: Optional[str] = Query(None, description="Con trỏ phân trang"),
    db: AsyncSession = Depends(get_db),
) -> PublicSellerReviewsCursorPage:
    service = ReviewService(db)
    return await service.get_public_seller_reviews(
        seller_id=user_id, limit=limit, cursor=cursor
    )
