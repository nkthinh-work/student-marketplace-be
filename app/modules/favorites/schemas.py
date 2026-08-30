from datetime import datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, ConfigDict

from app.modules.categories.schemas import CategorySummary
from app.modules.products.schemas import SellerSummary


class FavoriteProductResponse(BaseModel):
    """Product summary kèm thời điểm lưu tin."""
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
    favorited_at: datetime


class FavoriteListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[FavoriteProductResponse]
    next_cursor: Optional[str] = None
    has_more: bool


class FavoriteIdsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_ids: list[int]
