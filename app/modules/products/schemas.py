from datetime import datetime
from decimal import Decimal
import enum
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field

from app.modules.categories.schemas import CategorySummary
from app.modules.products.models import ListingType, ProductStatus


class SellerUpdatableStatus(str, enum.Enum):
    AVAILABLE = "AVAILABLE"
    HIDDEN = "HIDDEN"


class SellerSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    user_id: int
    full_name: str
    avatar_url: Optional[str] = None


class SellerDetailSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    user_id: int
    full_name: str
    avatar_url: Optional[str] = None
    default_meetup_area: Optional[str] = None
    created_at: datetime


class ProductCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category_id: int
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    listing_type: ListingType = ListingType.FIXED_PRICE
    price: Decimal = Field(..., ge=0)
    stock: int = Field(1, ge=0)


class ProductUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category_id: Optional[int] = None
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    listing_type: Optional[ListingType] = None
    price: Optional[Decimal] = Field(None, ge=0)
    stock: Optional[int] = Field(None, ge=0)
    status: Optional[SellerUpdatableStatus] = None


class ProductImageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    image_id: int
    product_id: int
    image_url: str
    detail_url: str
    sort_order: int
    is_thumbnail: bool


class ImageReorderItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_id: int
    sort_order: int


class ImageReorderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    images: list[ImageReorderItem] = Field(..., min_length=1)


class ProductSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    product_id: int
    title: str
    price: Decimal
    listing_type: str
    status: str
    available_stock: int
    thumbnail_url: Optional[str] = None
    category: CategorySummary
    seller: SellerSummary
    created_at: datetime


class ProductDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    product_id: int
    title: str
    description: Optional[str] = None
    listing_type: str
    price: Decimal
    available_stock: int
    status: str
    view_count: int
    images: list[ProductImageResponse]
    category: CategorySummary
    seller: SellerDetailSummary
    created_at: datetime
    updated_at: datetime


class SellerProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    product_id: int
    title: str
    description: Optional[str] = None
    listing_type: str
    price: Decimal
    stock: int
    reserved_stock: int
    available_stock: int
    status: str
    view_count: int
    thumbnail_url: Optional[str] = None
    category: CategorySummary
    created_at: datetime
    updated_at: datetime


class ProductListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ProductSummaryResponse]
    next_cursor: Optional[str] = None
    has_more: bool


class SellerProductListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[SellerProductResponse]
    next_cursor: Optional[str] = None
    has_more: bool
