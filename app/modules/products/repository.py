import base64
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Sequence
import unicodedata
import uuid
from sqlalchemy import (
    select,
    update,
    func,
    text,
    or_,
    and_,
    exists,
    case,
    String,
    false,
)
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.auctions.models import Auction, AuctionStatus
from app.modules.products.models import Product, ProductImage, ProductModerationStatus, ProductApprovalStatus
from app.modules.users.models import User, UserStatus
from app.modules.users.capability_models import UserCapabilityRestriction, CapabilityType



def _build_prefix_tsquery(cleaned_query: str):
    """
    Xây dựng biểu thức prefix tsquery an toàn cho PostgreSQL Full-Text Search.
    
    Quy trình an toàn:
    1. Chuỗi người dùng đã được chuẩn hoá NFC và strip.
    2. Nếu query chỉ có 1 ký tự: sử dụng plainto_tsquery('simple', cleaned_query) đối sánh từ nguyên bản
       (bảo toàn hành vi nhẹ nhàng, không prefix bừa bãi).
    3. Nếu query >= 2 ký tự:
       - plainto_tsquery('simple', cleaned_query) phân tích và bóc tách các lexeme hợp lệ,
         triệt tiêu toàn bộ ký tự đặc biệt (:, &, |, !, (, ), ', ", \\, +, -, c++, v.v.),
         tránh triệt để lỗi cú pháp tsquery syntax error.
       - Chuyển kết quả sang String và nối tiền tố ':*' vào token cuối cùng ('gi' -> 'gi':*, 'giáo' & 'tr' -> 'giáo' & 'tr':*).
       - Dùng CASE WHEN raw_tsquery_text = '' THEN NULL ELSE to_tsquery('simple', raw_tsquery_text || ':*') END
         để đảm bảo nếu chuỗi không chứa lexeme nào hợp lệ (ví dụ ': & | !'), biểu thức trả về NULL
         và điều kiện ts_vector @@ NULL trả về NULL/False an toàn tuyệt đối (0 bản ghi, không lỗi 500).
    """
    if len(cleaned_query) == 1:
        return func.plainto_tsquery("simple", cleaned_query)

    raw_tsquery_text = func.plainto_tsquery("simple", cleaned_query).cast(String)
    return case(
        (raw_tsquery_text == "", None),
        else_=func.to_tsquery("simple", raw_tsquery_text + ":*"),
    )



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
        for_update: bool = False,
    ) -> Optional[Product]:
        stmt = select(Product).where(Product.product_id == product_id)
        if not include_deleted:
            stmt = stmt.where(Product.is_deleted.is_(False))
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_public(
        self,
        category_id: Optional[int] = None,
        seller_id: Optional[int] = None,
        seller_public_id: Optional[uuid.UUID] = None,
        listing_type: Optional[str] = None,
        min_price: Optional[Decimal] = None,
        max_price: Optional[Decimal] = None,
        search_query: Optional[str] = None,
        limit: int = 20,
        cursor: Optional[tuple[datetime, int]] = None,
    ) -> tuple[list[Product], bool, Optional[tuple[datetime, int]]]:
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

        stmt = (
            select(Product)
            .join(User, Product.seller_id == User.user_id)
            .where(
                Product.is_deleted.is_(False),
                Product.status == "AVAILABLE",
                Product.moderation_status == ProductModerationStatus.CLEAR.value,
                Product.approval_status == ProductApprovalStatus.APPROVED.value,
                User.status == UserStatus.ACTIVE,
                ~sell_restricted_exists,
            )
        )

        if category_id is not None:
            stmt = stmt.where(Product.category_id == category_id)

        if seller_public_id is not None:
            if not isinstance(seller_public_id, uuid.UUID):
                try:
                    seller_public_id = uuid.UUID(str(seller_public_id))
                except (ValueError, TypeError, AttributeError):
                    seller_public_id = None
            if seller_public_id is not None:
                stmt = stmt.where(User.public_id == seller_public_id)
            else:
                stmt = stmt.where(false())
        elif seller_id is not None:
            stmt = stmt.where(Product.seller_id == seller_id)


        # Active auction EXISTS condition for public discovery
        active_auction_exists = exists(
            select(1).select_from(Auction).where(
                Auction.product_id == Product.product_id,
                Auction.status == AuctionStatus.ACTIVE.value,
            )
        )

        if listing_type is not None:
            if listing_type == "AUCTION":
                stmt = stmt.where(Product.listing_type == "AUCTION", active_auction_exists)
            else:
                stmt = stmt.where(Product.listing_type == listing_type)
        else:
            # Default public feed: FIXED_PRICE or ACTIVE AUCTION
            stmt = stmt.where(
                or_(
                    Product.listing_type == "FIXED_PRICE",
                    active_auction_exists,
                )
            )

        if min_price is not None:
            stmt = stmt.where(Product.price >= min_price)

        if max_price is not None:
            stmt = stmt.where(Product.price <= max_price)

        if search_query and search_query.strip():
            cleaned_query = unicodedata.normalize("NFC", search_query.strip())
            if cleaned_query:
                # Khớp biểu thức GIN full-text index trong PostgreSQL
                ts_vector = func.to_tsvector(
                    "simple",
                    func.coalesce(Product.title, "") + " " + func.coalesce(Product.description, ""),
                )
                stmt = stmt.where(
                    ts_vector.op("@@")(_build_prefix_tsquery(cleaned_query))
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
        approval_status: Optional[str] = None,
        limit: int = 20,
        cursor: Optional[tuple[datetime, int]] = None,
    ) -> tuple[list[Product], bool, Optional[tuple[datetime, int]]]:
        stmt = select(Product).where(
            Product.seller_id == seller_id,
            Product.is_deleted.is_(False),
        )

        if status is not None:
            stmt = stmt.where(Product.status == status)

        if approval_status is not None:
            stmt = stmt.where(Product.approval_status == approval_status)

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

    async def list_admin_queue(
        self,
        approval_status: str = "PENDING",
        limit: int = 20,
        cursor: Optional[tuple[datetime, int]] = None,
    ) -> tuple[list[Product], bool, Optional[tuple[datetime, int]]]:
        stmt = (
            select(Product)
            .where(
                Product.is_deleted.is_(False),
                Product.approval_status == approval_status,
            )
        )

        if approval_status == "PENDING":
            if cursor is not None:
                c_time, c_id = cursor
                if c_time.tzinfo is None:
                    c_time = c_time.replace(tzinfo=timezone.utc)
                stmt = stmt.where(
                    or_(
                        Product.submitted_for_review_at > c_time,
                        and_(
                            Product.submitted_for_review_at == c_time,
                            Product.product_id > c_id,
                        ),
                    )
                )
            stmt = stmt.order_by(
                Product.submitted_for_review_at.asc().nulls_last(),
                Product.product_id.asc(),
            )
        else:
            if cursor is not None:
                c_time, c_id = cursor
                if c_time.tzinfo is None:
                    c_time = c_time.replace(tzinfo=timezone.utc)
                stmt = stmt.where(
                    or_(
                        Product.reviewed_at < c_time,
                        and_(
                            Product.reviewed_at == c_time,
                            Product.product_id < c_id,
                        ),
                    )
                )
            stmt = stmt.order_by(
                Product.reviewed_at.desc().nulls_last(),
                Product.product_id.desc(),
            )

        stmt = stmt.limit(limit + 1)
        result = await self.db.execute(stmt)
        items = list(result.scalars().all())

        has_more = len(items) > limit
        if has_more:
            items = items[:limit]
            if approval_status == "PENDING":
                last_time = items[-1].submitted_for_review_at or items[-1].created_at
            else:
                last_time = items[-1].reviewed_at or items[-1].created_at
            next_cursor = (last_time, items[-1].product_id)
        else:
            next_cursor = None

        return items, has_more, next_cursor

    async def update(self, product: Product) -> Product:
        await self.db.flush()
        await self.db.refresh(product)
        return product

    async def update_view_count_floor(self, product_id: int, absolute_count: int) -> int:
        """
        Monotonically projects Redis absolute count to PostgreSQL products.view_count.
        Ensures view_count = GREATEST(view_count, :count).
        Uses raw SQL to preserve products.updated_at without false content modifications.
        Returns the number of affected rows.
        """
        stmt = text("""
            UPDATE products
            SET view_count = GREATEST(view_count, :count)
            WHERE product_id = :product_id AND is_deleted = FALSE
        """)
        result = await self.db.execute(stmt, {"count": absolute_count, "product_id": product_id})
        return result.rowcount


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

