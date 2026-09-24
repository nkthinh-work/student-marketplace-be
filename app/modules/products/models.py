from datetime import datetime
from decimal import Decimal
import enum
from typing import Optional, TYPE_CHECKING
from sqlalchemy import (
    BigInteger,
    Integer,
    SmallInteger,
    String,
    Text,
    Numeric,
    Boolean,
    DateTime,
    CheckConstraint,
    UniqueConstraint,
    Index,
    ForeignKey,
    text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

if TYPE_CHECKING:
    from app.modules.users.models import User
    from app.modules.categories.models import Category


class ListingType(str, enum.Enum):
    FIXED_PRICE = "FIXED_PRICE"
    AUCTION = "AUCTION"


class ProductStatus(str, enum.Enum):
    AVAILABLE = "AVAILABLE"
    HIDDEN = "HIDDEN"
    SOLD_OUT = "SOLD_OUT"


class ProductModerationStatus(str, enum.Enum):
    CLEAR = "CLEAR"
    BLOCKED = "BLOCKED"


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("price >= 0", name="chk_products_price"),
        CheckConstraint("stock >= 0", name="chk_products_stock"),
        CheckConstraint(
            "reserved_stock >= 0 AND reserved_stock <= stock",
            name="chk_products_reserved_stock",
        ),
        CheckConstraint(
            "listing_type IN ('FIXED_PRICE', 'AUCTION')",
            name="chk_products_listing_type",
        ),
        CheckConstraint(
            "status IN ('AVAILABLE', 'HIDDEN', 'SOLD_OUT')",
            name="chk_products_status",
        ),
        CheckConstraint(
            "moderation_status IN ('CLEAR', 'BLOCKED')",
            name="chk_products_moderation_status",
        ),
        Index(
            "ix_products_category_status",
            "category_id",
            "status",
            "is_deleted",
            "created_at",
        ),
        Index(
            "ix_products_seller_status",
            "seller_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_products_listing_type_status",
            "listing_type",
            "status",
            "is_deleted",
            "created_at",
        ),
        Index(
            "ix_products_search_gin",
            text("to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(description, ''))"),
            postgresql_using="gin",
        ),
    )

    product_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    seller_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.user_id", ondelete="RESTRICT"),
        nullable=False,
    )
    category_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("categories.category_id", ondelete="RESTRICT"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    listing_type: Mapped[str] = mapped_column(
        String(12),
        nullable=False,
        default=ListingType.FIXED_PRICE.value,
        server_default="FIXED_PRICE",
    )
    price: Mapped[Decimal] = mapped_column(
        Numeric(12, 0),
        nullable=False,
    )
    stock: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    reserved_stock: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    status: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default=ProductStatus.AVAILABLE.value,
        server_default="AVAILABLE",
    )
    moderation_status: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default=ProductModerationStatus.CLEAR.value,
        server_default="CLEAR",
    )
    view_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("FALSE"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    seller: Mapped["User"] = relationship(
        "User",
        lazy="selectin",
    )
    category: Mapped["Category"] = relationship(
        "Category",
        back_populates="products",
        lazy="selectin",
    )
    images: Mapped[list["ProductImage"]] = relationship(
        "ProductImage",
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="ProductImage.sort_order.asc(), ProductImage.image_id.asc()",
        lazy="selectin",
    )

    @property
    def available_stock(self) -> int:
        return max(0, self.stock - self.reserved_stock)


class ProductImage(Base):
    __tablename__ = "product_images"
    __table_args__ = (
        UniqueConstraint("product_id", "image_url", name="ux_product_images_product_url"),
        Index(
            "ux_product_images_thumbnail",
            "product_id",
            unique=True,
            postgresql_where=text("is_thumbnail = TRUE"),
        ),
        Index(
            "ix_product_images_product_sort",
            "product_id",
            "sort_order",
            "image_id",
        ),
    )

    image_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    product_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("products.product_id", ondelete="CASCADE"),
        nullable=False,
    )
    image_url: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )
    sort_order: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        default=0,
        server_default="0",
    )
    is_thumbnail: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("FALSE"),
    )

    product: Mapped["Product"] = relationship(
        "Product",
        back_populates="images",
    )
