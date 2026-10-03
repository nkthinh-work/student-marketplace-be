import uuid
from datetime import datetime, timezone
import logging
from typing import Optional
from sqlalchemy import func, select, or_, exists
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from app.core.banks import get_bank_by_bin, resolve_bank_bin
from app.modules.auctions.models import Auction, AuctionStatus
from app.modules.orders.models import Order, OrderItem, OrderStatus
from app.modules.products.models import (
    Product,
    ProductStatus,
    ListingType,
    ProductApprovalStatus,
    ProductModerationStatus,
)
from app.modules.reviews.models import Review
from app.modules.users.capability_models import UserCapabilityRestriction
from app.modules.users.models import User, UserStatus
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import (
    BankAccountResponse,
    BankAccountUpdate,
    PublicUserProfileResponse,
    SocialLinkItem,
    SoldProductListResponse,
    SoldProductSummary,
    SoldProductTransactionReview,
    UserUpdate,
)

logger = logging.getLogger("app")


class UserService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.user_repo = UserRepository(db)

    async def get_user_by_id(self, user_id: int) -> Optional[User]:
        return await self.user_repo.get_by_id(user_id)

    async def update_profile(self, user: User, payload: UserUpdate) -> User:
        update_data = payload.model_dump(exclude_unset=True)
        if not update_data:
            return user

        # Chặn cập nhật các trường nhạy cảm/hệ thống và trường do Google sync quản lý
        disallowed_fields = {
            "user_id",
            "public_id",
            "email",
            "role",
            "status",
            "avatar_url",
            "bank_bin",
            "bank_account_number",
            "bank_account_name",
            "created_at",
            "updated_at",
            "last_active_at",
        }
        filtered_data = {k: v for k, v in update_data.items() if k not in disallowed_fields}

        # Format social_links as list of dicts for JSON storage if present
        if "social_links" in filtered_data and filtered_data["social_links"] is not None:
            filtered_data["social_links"] = [
                item.model_dump() if hasattr(item, "model_dump") else dict(item)
                for item in filtered_data["social_links"]
            ]

        updated_user = await self.user_repo.update_user(user, filtered_data)
        await self.db.commit()
        await self.db.refresh(updated_user)
        return updated_user

    async def get_public_profile(self, public_id: uuid.UUID) -> PublicUserProfileResponse:
        user = await self.user_repo.get_by_public_id(public_id)
        if not user or user.status != UserStatus.ACTIVE:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Không tìm thấy người dùng.",
            )

        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        sell_restricted_exists = exists(
            select(1).select_from(UserCapabilityRestriction).where(
                UserCapabilityRestriction.user_id == user.user_id,
                UserCapabilityRestriction.capability == "SELL",
                UserCapabilityRestriction.revoked_at.is_(None),
                UserCapabilityRestriction.starts_at <= now_utc,
                or_(
                    UserCapabilityRestriction.expires_at.is_(None),
                    UserCapabilityRestriction.expires_at > now_utc,
                ),
            )
        )
        active_auction_exists = exists(
            select(1).select_from(Auction).where(
                Auction.product_id == Product.product_id,
                Auction.status == AuctionStatus.ACTIVE.value,
            )
        )
        active_listing_count = await self.db.scalar(
            select(func.count(Product.product_id)).where(
                Product.seller_id == user.user_id,
                Product.is_deleted.is_(False),
                Product.status == ProductStatus.AVAILABLE.value,
                Product.approval_status == ProductApprovalStatus.APPROVED.value,
                Product.moderation_status == ProductModerationStatus.CLEAR.value,
                ~sell_restricted_exists,
                or_(
                    Product.listing_type == ListingType.FIXED_PRICE.value,
                    active_auction_exists,
                ),
            )
        ) or 0

        completed_sold_count = await self.db.scalar(
            select(func.coalesce(func.sum(OrderItem.quantity), 0))
            .select_from(OrderItem)
            .join(Order, Order.order_id == OrderItem.order_id)
            .where(
                Order.seller_id == user.user_id,
                Order.status == OrderStatus.COMPLETED.value,
            )
        ) or 0

        # Query rating average and review count
        review_agg = await self.db.execute(
            select(
                func.avg(Review.rating),
                func.count(Review.review_id),
            ).where(Review.reviewee_id == user.user_id)
        )
        avg_val, cnt_val = review_agg.one()
        rating_average = round(float(avg_val), 1) if avg_val is not None else None
        review_count = int(cnt_val) if cnt_val is not None else 0

        # Public phone is revealed ONLY if user explicitly checked show_phone_publicly
        phone = user.phone if (user.show_phone_publicly and user.phone) else None

        social_links = None
        if user.social_links:
            social_links = [
                SocialLinkItem(**s) if isinstance(s, dict) else s
                for s in user.social_links
            ]

        return PublicUserProfileResponse(
            public_id=user.public_id,
            full_name=user.full_name,
            avatar_url=user.avatar_url,
            bio=user.bio,
            delivery_area=user.delivery_area,
            phone=phone,
            social_links=social_links,
            created_at=user.created_at,
            active_listing_count=int(active_listing_count),
            completed_sold_count=int(completed_sold_count),
            rating_average=rating_average,
            review_count=review_count,
        )

    async def get_sold_products(self, public_id: uuid.UUID) -> SoldProductListResponse:
        user = await self.user_repo.get_by_public_id(public_id)
        if not user or user.status != UserStatus.ACTIVE:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Không tìm thấy người dùng.",
            )

        stmt = (
            select(
                OrderItem.product_id,
                OrderItem.product_title,
                OrderItem.product_image_url,
                func.sum(OrderItem.quantity).label("total_sold_quantity"),
                func.max(Order.completed_at).label("last_sold_at"),
            )
            .select_from(OrderItem)
            .join(Order, Order.order_id == OrderItem.order_id)
            .where(
                Order.seller_id == user.user_id,
                Order.status == OrderStatus.COMPLETED.value,
            )

            .group_by(
                OrderItem.product_id,
                OrderItem.product_title,
                OrderItem.product_image_url,
            )
            .order_by(func.max(Order.completed_at).desc().nulls_last())
        )
        results = await self.db.execute(stmt)
        rows = results.all()
        if not rows:
            return SoldProductListResponse(items=[], total_count=0)

        product_ids = [r.product_id for r in rows]

        # Single batch query to fetch all reviews for these sold products (No N+1)
        review_stmt = (
            select(
                OrderItem.product_id,
                Review.rating,
                Review.comment,
                Review.created_at,
            )
            .select_from(Review)
            .join(Order, Order.order_id == Review.order_id)
            .join(OrderItem, OrderItem.order_id == Order.order_id)
            .where(
                Order.seller_id == user.user_id,
                Order.status == OrderStatus.COMPLETED.value,
                OrderItem.product_id.in_(product_ids),
            )
            .order_by(Review.created_at.desc(), Review.review_id.desc())
        )
        review_rows = (await self.db.execute(review_stmt)).all()

        reviews_by_product: dict[int, list[SoldProductTransactionReview]] = {}
        for r_row in review_rows:
            p_id = r_row.product_id
            if p_id not in reviews_by_product:
                reviews_by_product[p_id] = []
            reviews_by_product[p_id].append(
                SoldProductTransactionReview(
                    rating=r_row.rating,
                    comment=r_row.comment,
                    created_at=r_row.created_at,
                    verified_transaction=True,
                )
            )

        items = []
        for r in rows:
            prod_reviews = reviews_by_product.get(r.product_id, [])
            rev_count = len(prod_reviews)
            if rev_count > 0:
                avg_rating = round(sum(pr.rating for pr in prod_reviews) / rev_count, 1)
            else:
                avg_rating = None

            items.append(
                SoldProductSummary(
                    product_id=r.product_id,
                    product_title=r.product_title,
                    product_image_url=r.product_image_url,
                    total_sold_quantity=int(r.total_sold_quantity),
                    last_sold_at=r.last_sold_at,
                    rating_average=avg_rating,
                    review_count=rev_count,
                    recent_reviews=prod_reviews[:2],
                )
            )

        return SoldProductListResponse(items=items, total_count=len(items))

    async def get_bank_account(self, user: User) -> Optional[BankAccountResponse]:
        if not user.bank_bin or not user.bank_account_number or not user.bank_account_name:
            return None

        bank_info = get_bank_by_bin(user.bank_bin)
        return BankAccountResponse(
            bank_bin=user.bank_bin,
            bank_code=bank_info.code if bank_info else user.bank_bin,
            bank_name=bank_info.name if bank_info else "",
            bank_short_name=bank_info.short_name if bank_info else (bank_info.code if bank_info else user.bank_bin),
            account_number=user.bank_account_number,
            account_name=user.bank_account_name,
        )

    async def update_bank_account(self, user: User, payload: BankAccountUpdate) -> BankAccountResponse:
        resolved_bin = resolve_bank_bin(payload.bank_bin)
        if not resolved_bin:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ngân hàng không hợp lệ hoặc không được hỗ trợ.",
            )

        bank_info = get_bank_by_bin(resolved_bin)
        clean_account_number = payload.account_number.strip()
        clean_account_name = payload.account_name.strip()

        # Update and commit in transaction
        await self.user_repo.update_bank_account(
            user=user,
            bank_bin=resolved_bin,
            bank_account_number=clean_account_number,
            bank_account_name=clean_account_name,
        )
        await self.db.commit()
        await self.db.refresh(user)

        return BankAccountResponse(
            bank_bin=user.bank_bin,
            bank_code=bank_info.code if bank_info else user.bank_bin,
            bank_name=bank_info.name if bank_info else "",
            bank_short_name=bank_info.short_name if bank_info else user.bank_bin,
            account_number=user.bank_account_number,
            account_name=user.bank_account_name,
        )

    async def delete_bank_account(self, user: User) -> None:
        await self.user_repo.clear_bank_account(user)
        await self.db.commit()
        await self.db.refresh(user)
