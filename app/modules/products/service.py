from datetime import datetime, timezone
from decimal import Decimal
import logging
from typing import Optional
from uuid import UUID
import unicodedata
from fastapi import HTTPException, status, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.cloudinary import (
    upload_image,
    destroy_image,
    get_thumbnail_url,
    get_detail_image_url,
    CloudinaryNotConfiguredError,
    CloudinaryUploadError,
)
from app.modules.users.models import User
from app.modules.categories.repository import CategoryRepository
from app.modules.categories.schemas import CategorySummary
from app.modules.products.models import (
    Product,
    ProductImage,
    ProductStatus,
    ProductModerationStatus,
    ProductApprovalStatus,
)
from app.modules.reviews.models import Review
from app.modules.auctions.repository import AuctionRepository
from app.modules.users.capability_service import CapabilityService
from app.modules.notifications.models import NotificationType
from app.modules.notifications.service import (
    NotificationService,
    format_notification,
    safe_publish_user_notification,
)
from app.modules.products.repository import (
    ProductRepository,
    ProductImageRepository,
    encode_cursor,
    decode_cursor,
)
from app.core.config import settings
from app.core.redis import get_redis_client
from app.modules.products.view_counter import (
    register_view_in_redis,
    get_effective_view_count_from_redis,
    get_effective_view_counts_batch,
    build_viewer_token,
)
from app.modules.products.schemas import (
    ProductCreate,
    ProductUpdate,
    ProductSummaryResponse,
    ProductDetailResponse,
    ProductViewResponse,
    ProductListResponse,
    ProductImageResponse,
    SellerProductResponse,
    SellerProductListResponse,
    SellerAuctionSummary,
    SellerSummary,
    SellerDetailSummary,
    ImageReorderRequest,
    AdminProductApprovalSummary,
    AdminProductApprovalListResponse,
    AdminProductApprovalDetailResponse,
    AdminApprovalDecisionRequest,
)
from app.modules.auctions.models import Auction

logger = logging.getLogger("app")

ALLOWED_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


def format_product_summary(
    product: Product,
    effective_view_count: Optional[int] = None,
) -> ProductSummaryResponse:
    thumb_url = None
    if product.images:
        for img in product.images:
            if img.is_thumbnail:
                thumb_url = get_thumbnail_url(img.image_url)
                break
        if thumb_url is None and product.images:
            thumb_url = get_thumbnail_url(product.images[0].image_url)

    count = effective_view_count if effective_view_count is not None else product.view_count
    count = max(count or 0, 0)

    return ProductSummaryResponse(
        product_id=product.product_id,
        title=product.title,
        price=product.price,
        listing_type=product.listing_type,
        status=product.status,
        available_stock=product.available_stock,
        view_count=count,
        thumbnail_url=thumb_url,
        category=CategorySummary(
            category_id=product.category.category_id,
            name=product.category.name,
            slug=product.category.slug,
        ),
        seller=SellerSummary(
            user_id=product.seller.user_id,
            full_name=product.seller.full_name,
            avatar_url=product.seller.avatar_url,
        ),
        created_at=product.created_at,
    )


def format_seller_product(
    product: Product,
    auction: Optional[Auction] = None,
    effective_view_count: Optional[int] = None,
) -> SellerProductResponse:
    thumb_url = None
    if product.images:
        for img in product.images:
            if img.is_thumbnail:
                thumb_url = get_thumbnail_url(img.image_url)
                break
        if thumb_url is None and product.images:
            thumb_url = get_thumbnail_url(product.images[0].image_url)

    auction_summary = None
    if auction:
        curr_price = auction.starting_price
        if auction.bids:
            curr_price = max(b.amount for b in auction.bids)
        elif auction.final_price is not None:
            curr_price = auction.final_price

        auction_summary = SellerAuctionSummary(
            auction_id=auction.auction_id,
            status=auction.status,
            starting_price=auction.starting_price,
            bid_step=auction.bid_step,
            current_price=curr_price,
            starts_at=auction.starts_at,
            ends_at=auction.ends_at,
            winner_checkout_deadline=auction.winner_checkout_deadline,
            bid_count=len(auction.bids) if auction.bids else 0,
        )

    count = effective_view_count if effective_view_count is not None else product.view_count
    count = max(count or 0, 0)

    return SellerProductResponse(
        product_id=product.product_id,
        title=product.title,
        description=product.description,
        listing_type=product.listing_type,
        price=product.price,
        stock=product.stock,
        reserved_stock=product.reserved_stock,
        available_stock=product.available_stock,
        status=product.status,
        moderation_status=ProductModerationStatus(product.moderation_status),
        approval_status=ProductApprovalStatus(product.approval_status),
        submitted_for_review_at=product.submitted_for_review_at,
        reviewed_at=product.reviewed_at,
        review_note=product.review_note,
        view_count=count,
        thumbnail_url=thumb_url,
        category=CategorySummary(
            category_id=product.category.category_id,
            name=product.category.name,
            slug=product.category.slug,
        ),
        auction=auction_summary,
        created_at=product.created_at,
        updated_at=product.updated_at,
    )


def format_product_detail(
    product: Product,
    rating_average: Optional[float] = None,
    review_count: int = 0,
    effective_view_count: Optional[int] = None,
) -> ProductDetailResponse:
    formatted_images = [
        ProductImageResponse(
            image_id=img.image_id,
            product_id=img.product_id,
            image_url=img.image_url,
            detail_url=get_detail_image_url(img.image_url) or img.image_url,
            sort_order=img.sort_order,
            is_thumbnail=img.is_thumbnail,
        )
        for img in product.images
    ]

    return ProductDetailResponse(
        product_id=product.product_id,
        title=product.title,
        description=product.description,
        listing_type=product.listing_type,
        price=product.price,
        available_stock=product.available_stock,
        status=product.status,
        moderation_status=ProductModerationStatus(product.moderation_status),
        approval_status=ProductApprovalStatus(product.approval_status),
        view_count=effective_view_count if effective_view_count is not None else product.view_count,
        images=formatted_images,
        category=CategorySummary(
            category_id=product.category.category_id,
            name=product.category.name,
            slug=product.category.slug,
        ),
        seller=SellerDetailSummary(
            user_id=product.seller.user_id,
            full_name=product.seller.full_name,
            avatar_url=product.seller.avatar_url,
            delivery_area=product.seller.delivery_area,
            default_meetup_area=product.seller.default_meetup_area,
            created_at=product.seller.created_at,
            rating_average=rating_average,
            review_count=review_count,
        ),
        created_at=product.created_at,
        updated_at=product.updated_at,
    )


def format_admin_approval_summary(product: Product) -> AdminProductApprovalSummary:
    thumb_url = None
    if product.images:
        for img in product.images:
            if img.is_thumbnail:
                thumb_url = get_thumbnail_url(img.image_url)
                break
        if thumb_url is None and product.images:
            thumb_url = get_thumbnail_url(product.images[0].image_url)

    return AdminProductApprovalSummary(
        product_id=product.product_id,
        title=product.title,
        price=product.price,
        listing_type=product.listing_type,
        thumbnail_url=thumb_url,
        category=CategorySummary(
            category_id=product.category.category_id,
            name=product.category.name,
            slug=product.category.slug,
        ),
        seller=SellerSummary(
            user_id=product.seller.user_id,
            full_name=product.seller.full_name,
            avatar_url=product.seller.avatar_url,
        ),
        image_count=len(product.images) if product.images else 0,
        submitted_for_review_at=product.submitted_for_review_at,
        approval_status=ProductApprovalStatus(product.approval_status),
        created_at=product.created_at,
    )


def format_admin_approval_detail(product: Product) -> AdminProductApprovalDetailResponse:
    thumb_url = None
    if product.images:
        for img in product.images:
            if img.is_thumbnail:
                thumb_url = get_thumbnail_url(img.image_url)
                break
        if thumb_url is None and product.images:
            thumb_url = get_thumbnail_url(product.images[0].image_url)

    formatted_images = [
        ProductImageResponse(
            image_id=img.image_id,
            product_id=img.product_id,
            image_url=img.image_url,
            detail_url=get_detail_image_url(img.image_url) or img.image_url,
            sort_order=img.sort_order,
            is_thumbnail=img.is_thumbnail,
        )
        for img in product.images
    ]

    return AdminProductApprovalDetailResponse(
        product_id=product.product_id,
        title=product.title,
        description=product.description,
        listing_type=product.listing_type,
        price=product.price,
        stock=product.stock,
        status=product.status,
        approval_status=ProductApprovalStatus(product.approval_status),
        moderation_status=ProductModerationStatus(product.moderation_status),
        submitted_for_review_at=product.submitted_for_review_at,
        reviewed_by=product.reviewed_by,
        reviewed_at=product.reviewed_at,
        review_note=product.review_note,
        thumbnail_url=thumb_url,
        images=formatted_images,
        category=CategorySummary(
            category_id=product.category.category_id,
            name=product.category.name,
            slug=product.category.slug,
        ),
        seller=SellerDetailSummary(
            user_id=product.seller.user_id,
            full_name=product.seller.full_name,
            avatar_url=product.seller.avatar_url,
            delivery_area=product.seller.delivery_area,
            default_meetup_area=product.seller.default_meetup_area,
            created_at=product.seller.created_at,
            rating_average=None,
            review_count=0,
        ),
        created_at=product.created_at,
        updated_at=product.updated_at,
    )


class ProductService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.product_repo = ProductRepository(db)
        self.category_repo = CategoryRepository(db)
        self.image_repo = ProductImageRepository(db)
        self.auction_repo = AuctionRepository(db)

    async def create_product(
        self, seller: User, data: ProductCreate
    ) -> ProductDetailResponse:
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        if not await CapabilityService(self.db).can_user_sell(seller, now_utc=now_utc):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "SELL_RESTRICTED",
                    "message": "Tài khoản của bạn đang bị giới hạn quyền bán hàng.",
                },
            )

        category = await self.category_repo.get_by_id(data.category_id)
        if not category:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Category not found.",
            )

        product = Product(
            seller_id=seller.user_id,
            category_id=data.category_id,
            title=data.title.strip(),
            description=data.description.strip() if data.description else None,
            listing_type=data.listing_type.value,
            price=data.price,
            stock=data.stock,
            reserved_stock=0,
            status=ProductStatus.AVAILABLE.value,
            approval_status=ProductApprovalStatus.DRAFT.value,
            view_count=0,
            is_deleted=False,
        )

        created_product = await self.product_repo.create(product)
        await self.db.commit()
        await self.db.refresh(created_product)
        return format_product_detail(created_product)

    async def verify_product_visibility(
        self, product: Product, current_user: Optional[User] = None
    ) -> None:
        """
        Enforces canonical privacy and visibility checks for a product.
        Raises 404 HTTPException if the product is not visible to the current caller,
        preventing information leakage about hidden/blocked/deleted items.
        """
        # Approval gate: non-APPROVED products are hidden from third parties with privacy-safe 404
        if product.approval_status != ProductApprovalStatus.APPROVED.value:
            is_authorized = False
            if current_user:
                if current_user.user_id == product.seller_id or current_user.role == "ADMIN":
                    is_authorized = True
            if not is_authorized:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Product not found.",
                )

        # Privacy-safe check: Products from SELL-restricted sellers are hidden from third parties
        if not current_user or (current_user.user_id != product.seller_id and current_user.role != "ADMIN"):
            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
            if not await CapabilityService(self.db).can_user_sell(product.seller_id, now_utc=now_utc):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Product not found.",
                )

        # Moderation blocked product: only the owner seller may inspect it; safe 404 for all others
        if product.moderation_status == ProductModerationStatus.BLOCKED.value:
            if not current_user or current_user.user_id != product.seller_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Product not found.",
                )

        # If status is HIDDEN, only owner seller, admin, or winning bidder with checkout right may view
        if product.status == ProductStatus.HIDDEN.value:
            is_authorized = False
            if current_user:
                if current_user.user_id == product.seller_id or current_user.role == "ADMIN":
                    is_authorized = True
                else:
                    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
                    won_auction = await self.auction_repo.get_latest_ended_auction_with_active_winner_right(
                        product.product_id, now_utc=now_utc
                    )
                    if won_auction and won_auction.winner_id == current_user.user_id:
                        is_authorized = True

            if not is_authorized:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Product not found.",
                )

    async def get_product_detail(
        self, product_id: int, current_user: Optional[User] = None
    ) -> ProductDetailResponse:
        product = await self.product_repo.get_by_id(product_id)
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found.",
            )

        await self.verify_product_visibility(product, current_user=current_user)

        review_agg = await self.db.execute(
            select(
                func.avg(Review.rating),
                func.count(Review.review_id),
            ).where(Review.reviewee_id == product.seller_id)
        )
        avg_val, cnt_val = review_agg.one()
        rating_average = round(float(avg_val), 1) if avg_val is not None else None
        review_count = int(cnt_val) if cnt_val is not None else 0

        # Read effective view count from Redis (read-only, never increments on GET)
        effective_count = product.view_count
        try:
            redis = get_redis_client()
            if redis is not None:
                effective_count = await get_effective_view_count_from_redis(
                    redis, product.product_id, product.view_count
                )
        except Exception as e:
            logger.warning(
                "[get_product_detail] Redis read failed for product %s (%s): %s",
                product_id,
                type(e).__name__,
                e,
            )

        return format_product_detail(
            product,
            rating_average=rating_average,
            review_count=review_count,
            effective_view_count=effective_count,
        )

    async def register_product_view(
        self,
        product_id: int,
        current_user: Optional[User] = None,
        anonymous_viewer_id: Optional[UUID] = None,
    ) -> ProductViewResponse:
        """
        Registers a product view with 24h deduplication in Redis.
        Excludes seller views on own products and admin moderation views.
        Reuses canonical visibility rules to prevent existence leaks.
        Fails open gracefully if Redis is unavailable.
        """
        product = await self.product_repo.get_by_id(product_id)
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found.",
            )

        await self.verify_product_visibility(product, current_user=current_user)

        # Exclusions:
        # A. Seller viewing their own product
        # B. Admin viewing any product
        is_seller = current_user is not None and current_user.user_id == product.seller_id
        is_admin = current_user is not None and current_user.role == "ADMIN"

        viewer_token = build_viewer_token(
            current_user.user_id if current_user else None,
            anonymous_viewer_id,
        )

        should_count = (not is_seller) and (not is_admin) and (viewer_token is not None)

        try:
            redis = get_redis_client()
            if redis is None:
                # Redis unavailable -> fail-open: return DB count, counted=False
                return ProductViewResponse(view_count=product.view_count, counted=False)

            if not should_count:
                # Excluded from incrementing -> read effective count and return counted=False
                count = await get_effective_view_count_from_redis(
                    redis, product.product_id, product.view_count
                )
                return ProductViewResponse(view_count=count, counted=False)

            # Eligible unique viewer -> atomically register in Redis
            count, counted = await register_view_in_redis(
                redis=redis,
                product_id=product.product_id,
                viewer_token=viewer_token,
                db_view_count=product.view_count,
                dedupe_ttl=settings.PRODUCT_VIEW_DEDUPE_SECONDS,
            )
            return ProductViewResponse(view_count=count, counted=counted)
        except Exception as e:
            logger.warning(
                "[register_product_view] Redis error for product %s (%s): %s",
                product_id,
                type(e).__name__,
                e,
            )
            # Fail-open: do not disrupt product browsing
            return ProductViewResponse(view_count=product.view_count, counted=False)

    async def list_public_products(
        self,
        category_id: Optional[int] = None,
        seller_id: Optional[int] = None,
        listing_type: Optional[str] = None,
        min_price: Optional[Decimal] = None,
        max_price: Optional[Decimal] = None,
        search_query: Optional[str] = None,
        limit: int = 20,
        cursor: Optional[str] = None,
    ) -> ProductListResponse:
        if min_price is not None and max_price is not None and min_price > max_price:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="min_price cannot be greater than max_price.",
            )

        cursor_tuple = None
        if cursor:
            try:
                cursor_tuple = decode_cursor(cursor)
            except ValueError as e:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="Invalid pagination cursor.",
                ) from e

        normalized_query = None
        if search_query and search_query.strip():
            normalized_query = unicodedata.normalize("NFC", search_query.strip())

        items, has_more, next_cursor_tuple = await self.product_repo.list_public(
            category_id=category_id,
            seller_id=seller_id,
            listing_type=listing_type,
            min_price=min_price,
            max_price=max_price,
            search_query=normalized_query,
            limit=limit,
            cursor=cursor_tuple,
        )

        next_cursor_str = (
            encode_cursor(next_cursor_tuple[0], next_cursor_tuple[1])
            if next_cursor_tuple
            else None
        )

        effective_counts: dict[int, int] = {}
        if items:
            db_counts = {p.product_id: p.view_count for p in items}
            redis = get_redis_client()
            effective_counts = await get_effective_view_counts_batch(redis, db_counts)

        return ProductListResponse(
            items=[
                format_product_summary(
                    p,
                    effective_view_count=effective_counts.get(p.product_id, p.view_count),
                )
                for p in items
            ],
            next_cursor=next_cursor_str,
            has_more=has_more,
        )

    async def list_seller_products(
        self,
        seller: User,
        status_filter: Optional[str] = None,
        approval_status_filter: Optional[str] = None,
        limit: int = 20,
        cursor: Optional[str] = None,
    ) -> SellerProductListResponse:
        cursor_tuple = None
        if cursor:
            try:
                cursor_tuple = decode_cursor(cursor)
            except ValueError as e:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="Invalid pagination cursor.",
                ) from e

        items, has_more, next_cursor_tuple = await self.product_repo.list_by_seller(
            seller_id=seller.user_id,
            status=status_filter,
            approval_status=approval_status_filter,
            limit=limit,
            cursor=cursor_tuple,
        )

        next_cursor_str = (
            encode_cursor(next_cursor_tuple[0], next_cursor_tuple[1])
            if next_cursor_tuple
            else None
        )

        auction_pids = [p.product_id for p in items if p.listing_type == "AUCTION"]
        auction_map = {}
        if auction_pids:
            auction_map = await self.auction_repo.get_active_or_latest_by_product_ids(auction_pids)

        effective_counts: dict[int, int] = {}
        if items:
            db_counts = {p.product_id: p.view_count for p in items}
            redis = get_redis_client()
            effective_counts = await get_effective_view_counts_batch(redis, db_counts)

        return SellerProductListResponse(
            items=[
                format_seller_product(
                    p,
                    auction=auction_map.get(p.product_id),
                    effective_view_count=effective_counts.get(p.product_id, p.view_count),
                )
                for p in items
            ],
            next_cursor=next_cursor_str,
            has_more=has_more,
        )

    async def update_product(
        self, product_id: int, seller: User, data: ProductUpdate
    ) -> ProductDetailResponse:
        product = await self.product_repo.get_by_id(product_id, for_update=True)
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found.",
            )

        if product.seller_id != seller.user_id and seller.role != "ADMIN":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to update this product.",
            )

        # Auction guards: check if active/scheduled auction exists
        active_auction = await self.auction_repo.get_active_auction_by_product_id(product.product_id)
        if active_auction:
            bid_count = await self.auction_repo.count_bids(active_auction.auction_id)
            if bid_count > 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Không thể chỉnh sửa thông tin sản phẩm khi phiên đấu giá đã có lượt đặt giá.",
                )
            if data.status == ProductStatus.HIDDEN:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Không thể ẩn sản phẩm khi đang có phiên đấu giá. Vui lòng hủy đấu giá trước.",
                )
            if data.price is not None or data.stock is not None or data.listing_type is not None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Không thể thay đổi giá, tồn kho hoặc hình thức bán khi đang có phiên đấu giá.",
                )

        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        won_auction = await self.auction_repo.get_latest_ended_auction_with_active_winner_right(
            product.product_id, now_utc=now_utc
        )
        if won_auction:
            if data.status == ProductStatus.HIDDEN:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Không thể ẩn sản phẩm khi người thắng đấu giá vẫn còn thời hạn đặt mua.",
                )
            if data.price is not None or data.stock is not None or data.listing_type is not None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Không thể thay đổi giá, tồn kho hoặc hình thức bán khi đang chờ người thắng đặt mua.",
                )

        # Check moderation-sensitive field changes
        is_sensitive_edit = False
        if data.category_id is not None and data.category_id != product.category_id:
            is_sensitive_edit = True
        if data.title is not None and data.title.strip() != product.title:
            is_sensitive_edit = True
        if data.description is not None:
            new_desc = data.description.strip() if data.description else None
            if new_desc != product.description:
                is_sensitive_edit = True
        if data.listing_type is not None and data.listing_type.value != product.listing_type:
            is_sensitive_edit = True
        if data.price is not None and data.price != product.price:
            is_sensitive_edit = True

        if is_sensitive_edit:
            # Active/Scheduled auction guard (Section 38)
            active_or_sched = await self.auction_repo.get_active_auction_by_product_id(product.product_id)
            if active_or_sched:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Không thể thay đổi thông tin kiểm duyệt của sản phẩm khi đang có phiên đấu giá.",
                )
            if product.approval_status in (
                ProductApprovalStatus.APPROVED.value,
                ProductApprovalStatus.PENDING.value,
                ProductApprovalStatus.REJECTED.value,
            ):
                product.approval_status = ProductApprovalStatus.DRAFT.value
                product.submitted_for_review_at = None

        if data.category_id is not None:
            category = await self.category_repo.get_by_id(data.category_id)
            if not category:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Category not found.",
                )
            product.category_id = data.category_id

        if data.title is not None:
            product.title = data.title.strip()
        if data.description is not None:
            product.description = data.description.strip() if data.description else None
        if data.listing_type is not None:
            product.listing_type = data.listing_type.value
        if data.price is not None:
            product.price = data.price
        if data.stock is not None:
            product.stock = data.stock
        if data.status is not None:
            product.status = data.status.value

        updated_product = await self.product_repo.update(product)
        await self.db.commit()
        await self.db.refresh(updated_product)
        return format_product_detail(updated_product)

    async def soft_delete_product(self, product_id: int, seller: User) -> None:
        product = await self.product_repo.get_by_id(product_id, for_update=True)
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found.",
            )

        if product.seller_id != seller.user_id and seller.role != "ADMIN":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to delete this product.",
            )

        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

        # 1. Auction guard: check if active/scheduled auction exists
        active_auction = await self.auction_repo.get_active_auction_by_product_id(product.product_id)
        if active_auction:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Không thể xóa sản phẩm khi đang có phiên đấu giá. Vui lòng hủy đấu giá trước.",
            )

        # 2. Auction guard: check if ended auction with still-active winner checkout right exists
        won_auction = await self.auction_repo.get_latest_ended_auction_with_active_winner_right(
            product.product_id, now_utc=now_utc
        )
        if won_auction:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Không thể xóa tin khi người thắng đấu giá vẫn còn thời hạn đặt mua.",
            )

        product.is_deleted = True
        await self.product_repo.update(product)
        await self.db.commit()

    async def upload_product_image(
        self, product_id: int, seller: User, file: UploadFile
    ) -> ProductImageResponse:
        product = await self.product_repo.get_by_id(product_id)
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found.",
            )

        if product.seller_id != seller.user_id and seller.role != "ADMIN":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to upload images for this product.",
            )

        # Auction guard (Section 38): check if active/scheduled auction exists
        active_auction = await self.auction_repo.get_active_auction_by_product_id(product.product_id)
        if active_auction:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Không thể tải thêm hình ảnh khi sản phẩm đang có phiên đấu giá.",
            )

        if file.content_type not in ALLOWED_IMAGE_MIME_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid image type. Allowed types: {', '.join(ALLOWED_IMAGE_MIME_TYPES)}",
            )

        file_bytes = await file.read()
        if len(file_bytes) > MAX_IMAGE_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Image file size exceeds the maximum allowed limit (10MB).",
            )

        try:
            upload_result = upload_image(
                file_bytes, folder_key="products", product_id=product_id
            )
        except CloudinaryNotConfiguredError as e:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Image storage service is not configured.",
            ) from e
        except CloudinaryUploadError as e:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Failed to upload image to storage service: {e}",
            ) from e

        image_url = upload_result.get("secure_url")
        public_id = upload_result.get("public_id")

        try:
            image_count = await self.image_repo.count_by_product(product_id)
            max_order = await self.image_repo.get_max_sort_order(product_id)
            is_thumb = image_count == 0  # Ảnh đầu tiên mặc định làm thumbnail

            new_image = ProductImage(
                product_id=product_id,
                image_url=image_url,
                sort_order=max_order + 1,
                is_thumbnail=is_thumb,
            )
            created_image = await self.image_repo.create(new_image)

            # Invalidate approval in the same transaction
            if product.approval_status in (
                ProductApprovalStatus.APPROVED.value,
                ProductApprovalStatus.PENDING.value,
                ProductApprovalStatus.REJECTED.value,
            ):
                product.approval_status = ProductApprovalStatus.DRAFT.value
                product.submitted_for_review_at = None
                await self.product_repo.update(product)

            await self.db.commit()
            await self.db.refresh(created_image)

            return ProductImageResponse(
                image_id=created_image.image_id,
                product_id=created_image.product_id,
                image_url=created_image.image_url,
                detail_url=get_detail_image_url(created_image.image_url) or created_image.image_url,
                sort_order=created_image.sort_order,
                is_thumbnail=created_image.is_thumbnail,
            )
        except Exception as e:
            await self.db.rollback()
            # Xóa ảnh Cloudinary để bồi hoàn nếu lưu DB thất bại
            if public_id:
                logger.warning(
                    f"DB insert failed after Cloudinary upload. Cleaning up public_id: {public_id}"
                )
                destroy_image(public_id)
            logger.error(f"Failed to save product image to DB: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to save image record.",
            ) from e

    async def delete_product_image(
        self, product_id: int, image_id: int, seller: User
    ) -> None:
        product = await self.product_repo.get_by_id(product_id)
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found.",
            )

        if product.seller_id != seller.user_id and seller.role != "ADMIN":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to delete images from this product.",
            )

        # Auction guard (Section 38): check if active/scheduled auction exists
        active_auction = await self.auction_repo.get_active_auction_by_product_id(product.product_id)
        if active_auction:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Không thể xóa hình ảnh khi sản phẩm đang có phiên đấu giá.",
            )

        image = await self.image_repo.get_by_product_and_id(product_id, image_id)
        if not image:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Image not found on this product.",
            )

        was_thumbnail = image.is_thumbnail

        await self.image_repo.delete(image)

        # Tự động chọn ảnh kế tiếp làm thumbnail nếu ảnh bị xóa là thumbnail
        if was_thumbnail:
            remaining_images = await self.image_repo.list_by_product(product_id)
            if remaining_images:
                next_thumb = remaining_images[0]
                await self.image_repo.set_thumbnail(product_id, next_thumb.image_id)

        # Invalidate approval in the same transaction
        if product.approval_status in (
            ProductApprovalStatus.APPROVED.value,
            ProductApprovalStatus.PENDING.value,
            ProductApprovalStatus.REJECTED.value,
        ):
            product.approval_status = ProductApprovalStatus.DRAFT.value
            product.submitted_for_review_at = None
            await self.product_repo.update(product)

        await self.db.commit()

    async def set_product_thumbnail(
        self, product_id: int, image_id: int, seller: User
    ) -> None:
        product = await self.product_repo.get_by_id(product_id)
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found.",
            )

        if product.seller_id != seller.user_id and seller.role != "ADMIN":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to modify this product.",
            )

        image = await self.image_repo.get_by_product_and_id(product_id, image_id)
        if not image:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Image not found on this product.",
            )

        await self.image_repo.set_thumbnail(product_id, image_id)
        await self.db.commit()

    async def reorder_product_images(
        self, product_id: int, seller: User, data: ImageReorderRequest
    ) -> None:
        product = await self.product_repo.get_by_id(product_id)
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found.",
            )

        if product.seller_id != seller.user_id and seller.role != "ADMIN":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to reorder images on this product.",
            )

        current_images = await self.image_repo.list_by_product(product_id)
        current_image_ids = {img.image_id for img in current_images}

        # Kiểm tra toàn bộ image_id thuộc về product
        for item in data.images:
            if item.image_id not in current_image_ids:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Image {item.image_id} does not belong to this product.",
                )

        reorder_items = [(item.image_id, item.sort_order) for item in data.images]
        await self.image_repo.reorder_images(product_id, reorder_items)
        await self.db.commit()

    async def submit_for_review(
        self, product_id: int, seller: User
    ) -> SellerProductResponse:
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        if not await CapabilityService(self.db).can_user_sell(seller, now_utc=now_utc):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "SELL_RESTRICTED",
                    "message": "Tài khoản của bạn đang bị giới hạn quyền bán hàng.",
                },
            )

        product = await self.product_repo.get_by_id(product_id, for_update=True)
        if not product or product.is_deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found.",
            )

        if product.seller_id != seller.user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to submit this product for review.",
            )

        if product.moderation_status == ProductModerationStatus.BLOCKED.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Tin đăng đang bị quản trị viên ẩn, không thể gửi duyệt.",
            )

        if product.approval_status not in (
            ProductApprovalStatus.DRAFT.value,
            ProductApprovalStatus.REJECTED.value,
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Tin đăng đang ở trạng thái '{product.approval_status}', không thể gửi duyệt.",
            )

        product.approval_status = ProductApprovalStatus.PENDING.value
        product.submitted_for_review_at = datetime.now(timezone.utc)
        product.review_note = None

        notif_service = NotificationService(self.db)
        admin_snapshots = await notif_service.notify_admins(
            title="Có tin đăng mới chờ duyệt",
            body="Một tin đăng mới đang chờ quản trị viên kiểm duyệt.",
            ref_type="ADMIN_PRODUCT_APPROVAL",
            ref_id=product.product_id,
        )

        updated_product = await self.product_repo.update(product)
        await self.db.commit()
        await self.db.refresh(updated_product)

        # Post-commit best-effort realtime notification dispatch
        for admin_id, notif_dto in admin_snapshots:
            await safe_publish_user_notification(admin_id, notif_dto)

        return format_seller_product(updated_product)

    async def list_admin_approvals(
        self,
        approval_status: str = "PENDING",
        limit: int = 20,
        cursor: Optional[str] = None,
    ) -> AdminProductApprovalListResponse:
        cursor_tuple = None
        if cursor:
            try:
                cursor_tuple = decode_cursor(cursor)
            except ValueError as e:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="Invalid pagination cursor.",
                ) from e

        items, has_more, next_cursor_tuple = await self.product_repo.list_admin_queue(
            approval_status=approval_status,
            limit=limit,
            cursor=cursor_tuple,
        )

        next_cursor_str = (
            encode_cursor(next_cursor_tuple[0], next_cursor_tuple[1])
            if next_cursor_tuple
            else None
        )

        return AdminProductApprovalListResponse(
            items=[format_admin_approval_summary(p) for p in items],
            next_cursor=next_cursor_str,
            has_more=has_more,
        )

    async def get_admin_approval_detail(
        self, product_id: int
    ) -> AdminProductApprovalDetailResponse:
        product = await self.product_repo.get_by_id(product_id)
        if not product or product.is_deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found.",
            )
        return format_admin_approval_detail(product)

    async def admin_decision(
        self, product_id: int, admin: User, data: AdminApprovalDecisionRequest
    ) -> AdminProductApprovalDetailResponse:
        product = await self.product_repo.get_by_id(product_id, for_update=True)
        if not product or product.is_deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found.",
            )

        if product.approval_status != ProductApprovalStatus.PENDING.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Tin đăng đang ở trạng thái '{product.approval_status}', không thể xử lý duyệt.",
            )

        now_utc = datetime.now(timezone.utc)
        if data.decision == "APPROVE":
            product.approval_status = ProductApprovalStatus.APPROVED.value
            product.reviewed_by = admin.user_id
            product.reviewed_at = now_utc
            product.review_note = None

            if product.status == ProductStatus.AVAILABLE.value:
                notif_title = "Tin đăng đã được duyệt"
                notif_body = f'"{product.title}" đã được duyệt và có thể hiển thị trên Chợ PTITers.'
            else:
                notif_title = "Tin đăng đã được duyệt"
                notif_body = "Tin đăng đã được duyệt. Bạn có thể hiển thị tin khi sẵn sàng."
        elif data.decision == "REJECT":
            if not data.note or not data.note.strip():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Vui lòng cung cấp lý do từ chối (1..500 ký tự).",
                )
            note = data.note.strip()
            if len(note) > 500:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Lý do từ chối không được vượt quá 500 ký tự.",
                )
            product.approval_status = ProductApprovalStatus.REJECTED.value
            product.reviewed_by = admin.user_id
            product.reviewed_at = now_utc
            product.review_note = note

            notif_title = "Tin đăng cần được chỉnh sửa"
            notif_body = f'Tin đăng "{product.title}" cần chỉnh sửa trước khi có thể hiển thị.'
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Quyết định không hợp lệ.",
            )

        notif_service = NotificationService(self.db)
        seller_notif = await notif_service.create_notification(
            user_id=product.seller_id,
            type="SYSTEM",
            title=notif_title,
            body=notif_body,
            ref_type="PRODUCT_APPROVAL",
            ref_id=product.product_id,
        )

        updated_product = await self.product_repo.update(product)
        await self.db.commit()
        await self.db.refresh(updated_product)

        # Post-commit best-effort realtime notification dispatch
        notif_dto = format_notification(seller_notif)
        await safe_publish_user_notification(product.seller_id, notif_dto)

        return format_admin_approval_detail(updated_product)
