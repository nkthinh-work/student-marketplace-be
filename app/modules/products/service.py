from datetime import datetime, timezone
from decimal import Decimal
import logging
from typing import Optional
from fastapi import HTTPException, status, UploadFile
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
from app.modules.products.models import Product, ProductImage, ProductStatus
from app.modules.auctions.repository import AuctionRepository
from app.modules.products.repository import (
    ProductRepository,
    ProductImageRepository,
    encode_cursor,
    decode_cursor,
)
from app.modules.products.schemas import (
    ProductCreate,
    ProductUpdate,
    ProductSummaryResponse,
    ProductDetailResponse,
    ProductListResponse,
    ProductImageResponse,
    SellerProductResponse,
    SellerProductListResponse,
    SellerSummary,
    SellerDetailSummary,
    ImageReorderRequest,
)

logger = logging.getLogger("app")

ALLOWED_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


def format_product_summary(product: Product) -> ProductSummaryResponse:
    thumb_url = None
    if product.images:
        for img in product.images:
            if img.is_thumbnail:
                thumb_url = get_thumbnail_url(img.image_url)
                break
        if thumb_url is None and product.images:
            thumb_url = get_thumbnail_url(product.images[0].image_url)

    return ProductSummaryResponse(
        product_id=product.product_id,
        title=product.title,
        price=product.price,
        listing_type=product.listing_type,
        status=product.status,
        available_stock=product.available_stock,
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


def format_seller_product(product: Product) -> SellerProductResponse:
    thumb_url = None
    if product.images:
        for img in product.images:
            if img.is_thumbnail:
                thumb_url = get_thumbnail_url(img.image_url)
                break
        if thumb_url is None and product.images:
            thumb_url = get_thumbnail_url(product.images[0].image_url)

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
        view_count=product.view_count,
        thumbnail_url=thumb_url,
        category=CategorySummary(
            category_id=product.category.category_id,
            name=product.category.name,
            slug=product.category.slug,
        ),
        created_at=product.created_at,
        updated_at=product.updated_at,
    )


def format_product_detail(product: Product) -> ProductDetailResponse:
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
        view_count=product.view_count,
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
            view_count=0,
            is_deleted=False,
        )

        created_product = await self.product_repo.create(product)
        await self.db.commit()
        await self.db.refresh(created_product)
        return format_product_detail(created_product)

    async def get_product_detail(
        self, product_id: int, current_user: Optional[User] = None
    ) -> ProductDetailResponse:
        product = await self.product_repo.get_by_id(product_id)
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found.",
            )

        # Nếu status HIDDEN, cho phép seller sở hữu, admin, hoặc winner có quyền checkout xem
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

        return format_product_detail(product)

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

        items, has_more, next_cursor_tuple = await self.product_repo.list_public(
            category_id=category_id,
            seller_id=seller_id,
            listing_type=listing_type,
            min_price=min_price,
            max_price=max_price,
            search_query=search_query,
            limit=limit,
            cursor=cursor_tuple,
        )

        next_cursor_str = (
            encode_cursor(next_cursor_tuple[0], next_cursor_tuple[1])
            if next_cursor_tuple
            else None
        )

        return ProductListResponse(
            items=[format_product_summary(p) for p in items],
            next_cursor=next_cursor_str,
            has_more=has_more,
        )

    async def list_seller_products(
        self,
        seller: User,
        status_filter: Optional[str] = None,
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
            limit=limit,
            cursor=cursor_tuple,
        )

        next_cursor_str = (
            encode_cursor(next_cursor_tuple[0], next_cursor_tuple[1])
            if next_cursor_tuple
            else None
        )

        return SellerProductListResponse(
            items=[format_seller_product(p) for p in items],
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
