from datetime import datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.orders.models import (
    FulfillmentMethod,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
)


class CreateOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: int
    quantity: int = Field(1, ge=1)
    payment_method: Optional[PaymentMethod] = None
    fulfillment_method: FulfillmentMethod = FulfillmentMethod.MEETUP
    meetup_place: Optional[str] = Field(None, max_length=255)
    meetup_time: Optional[datetime] = None
    shipping_address: Optional[str] = Field(None, max_length=500)
    contact_name: str = Field(..., min_length=1, max_length=100)
    contact_phone: str = Field(..., min_length=1, max_length=20)
    buyer_note: Optional[str] = Field(None, max_length=500)

    @model_validator(mode="after")
    def validate_order_rules(self) -> "CreateOrderRequest":
        if self.fulfillment_method == FulfillmentMethod.MEETUP:
            if not self.meetup_place or not self.meetup_place.strip():
                raise ValueError("Vui lòng nhập địa điểm hẹn gặp.")
        if self.fulfillment_method == FulfillmentMethod.SHIPPING:
            if not self.shipping_address or not self.shipping_address.strip():
                raise ValueError("Vui lòng nhập địa chỉ giao hàng.")
        if not self.contact_name or not self.contact_name.strip():
            raise ValueError("Tên người nhận không được để trống.")
        if not self.contact_phone or not self.contact_phone.strip():
            raise ValueError("Số điện thoại liên hệ không được để trống.")
        return self


class UpdateOrderTransactionTermsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fulfillment_method: Optional[FulfillmentMethod] = None
    payment_method: Optional[PaymentMethod] = None
    meetup_place: Optional[str] = Field(None, max_length=255)
    meetup_time: Optional[datetime] = None
    shipping_address: Optional[str] = Field(None, max_length=500)
    payment_note: Optional[str] = Field(None, max_length=255)


class ConfirmOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payment_note: Optional[str] = Field(None, max_length=255)


class CancelOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cancel_reason: str = Field(..., min_length=1, max_length=255)

    @model_validator(mode="after")
    def validate_reason(self) -> "CancelOrderRequest":
        if not self.cancel_reason or not self.cancel_reason.strip():
            raise ValueError("Lý do hủy đơn không được để trống.")
        return self


class OrderItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    order_item_id: int
    product_id: int
    product_title: str
    product_image_url: Optional[str] = None
    quantity: int
    price_at_purchase: Decimal


class OrderStatusHistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    history_id: int
    from_status: Optional[str] = None
    to_status: str
    changed_by: Optional[int] = None
    note: Optional[str] = None
    created_at: datetime


class OrderPaymentBankResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    bank_bin: str
    bank_code: str
    bank_name: str
    bank_short_name: str
    account_number: str
    account_name: str
    qr_url: Optional[str] = None


class OrderSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    order_id: int
    order_code: str
    buyer_id: int
    seller_id: int
    status: str
    payment_method: str
    payment_status: str
    fulfillment_method: str
    total_amount: Decimal
    item: OrderItemResponse
    created_at: datetime
    updated_at: datetime


class OrderDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    order_id: int
    order_code: str
    buyer_id: int
    buyer_name: str
    buyer_avatar_url: Optional[str] = None
    seller_id: int
    seller_name: str
    seller_avatar_url: Optional[str] = None
    status: str
    payment_method: str
    payment_status: str
    payment_receipt_url: Optional[str] = None
    receipt_uploaded_at: Optional[datetime] = None
    paid_confirmed_at: Optional[datetime] = None
    payment_note: Optional[str] = None
    payment_bank: Optional[OrderPaymentBankResponse] = None
    fulfillment_method: str
    meetup_place: Optional[str] = None
    meetup_time: Optional[datetime] = None
    shipping_address: Optional[str] = None
    contact_name: str
    contact_phone: str
    buyer_note: Optional[str] = None
    total_amount: Decimal
    auto_cancel_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    cancelled_by: Optional[str] = None
    cancel_reason: Optional[str] = None
    items: list[OrderItemResponse]
    status_history: list[OrderStatusHistoryResponse]
    created_at: datetime
    updated_at: datetime


class OrderCursorPage(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    items: list[OrderSummaryResponse]
    next_cursor: Optional[str] = None
    has_more: bool
