from datetime import datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field

from app.core.privacy import anonymize_name as core_anonymize_name
from app.modules.orders.models import FulfillmentMethod, PaymentMethod


def anonymize_name(full_name: Optional[str]) -> str:
    return core_anonymize_name(full_name, default="Người đặt giá")


class AuctionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: int
    bid_step: Decimal = Field(..., gt=0, description="Bước giá tối thiểu (phải > 0)")
    duration_minutes: Optional[int] = Field(None, gt=0, description="Thời lượng đấu giá tính bằng phút (Bắt đầu ngay)")
    starts_at: Optional[datetime] = Field(None, description="Thời điểm bắt đầu (legacy/manual)")
    ends_at: Optional[datetime] = Field(None, description="Thời điểm kết thúc (legacy/manual)")


class PlaceBidRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: Decimal = Field(..., gt=0, description="Giá muốn đặt (phải > 0)")


class WinnerCheckoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payment_method: PaymentMethod = Field(..., description="Phương thức thanh toán")
    fulfillment_method: FulfillmentMethod = Field(..., description="Hình thức giao nhận")
    meetup_place: Optional[str] = Field(None, max_length=255, description="Địa điểm hẹn gặp khi MEETUP")
    meetup_time: Optional[datetime] = Field(None, description="Thời gian hẹn gặp khi MEETUP")
    shipping_address: Optional[str] = Field(None, max_length=500, description="Địa chỉ giao hàng khi SHIPPING")
    contact_name: str = Field(..., min_length=1, max_length=100, description="Tên người nhận")
    contact_phone: str = Field(..., min_length=1, max_length=20, description="Số điện thoại liên hệ")
    buyer_note: Optional[str] = Field(None, max_length=500, description="Ghi chú đơn hàng")


class AuctionBidResponse(BaseModel):
    bid_id: int
    auction_id: int
    bidder_display: str
    bidder_avatar_url: Optional[str] = None
    amount: Decimal
    created_at: datetime
    is_current_user: bool = False
    is_highest: bool = False


class AuctionBidCursorPage(BaseModel):
    items: list[AuctionBidResponse]
    next_cursor: Optional[str] = None
    has_more: bool = False


class AuctionDetailResponse(BaseModel):
    auction_id: int
    product_id: int
    status: str
    starting_price: Decimal
    bid_step: Decimal
    current_price: Decimal
    highest_bid: Optional[Decimal] = None
    bid_count: int
    minimum_next_bid: Decimal
    starts_at: datetime
    ends_at: datetime
    has_winner: bool = False
    final_price: Optional[Decimal] = None
    winner_checkout_deadline: Optional[datetime] = None
    is_current_user_winner: bool = False
    is_current_user_highest_bidder: bool = False
    highest_bidder_display: Optional[str] = None
    server_time: datetime
    winner_checkout_state: Optional[str] = None
    winner_order_id: Optional[int] = None


class WonAuctionItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    auction_id: int
    product_id: int
    product_title: str
    product_image_url: Optional[str] = None
    final_price: Decimal
    winner_checkout_deadline: datetime
    server_time: datetime
