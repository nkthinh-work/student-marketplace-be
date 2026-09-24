from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ReviewCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rating: int = Field(..., ge=1, le=5, description="Đánh giá từ 1 đến 5 sao")
    comment: Optional[str] = Field(None, max_length=1000, description="Nội dung nhận xét (tối đa 1000 ký tự)")

    @field_validator("comment", mode="after")
    @classmethod
    def normalize_comment(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        trimmed = v.strip()
        return trimmed if trimmed else None


class ReviewUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rating: Optional[int] = Field(None, ge=1, le=5, description="Đánh giá từ 1 đến 5 sao")
    comment: Optional[str] = Field(None, max_length=1000, description="Nội dung nhận xét")

    @field_validator("rating", mode="before")
    @classmethod
    def validate_rating_not_null(cls, v: Any) -> Any:
        if v is None:
            raise ValueError("Số sao đánh giá không được để trống (null).")
        return v

    @field_validator("comment", mode="after")
    @classmethod
    def normalize_comment(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        trimmed = v.strip()
        return trimmed if trimmed else None

    @model_validator(mode="after")
    def check_at_least_one_field(self) -> "ReviewUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("Phải cung cấp ít nhất một trường để cập nhật (rating hoặc comment).")
        return self


class OrderReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    review_id: int
    order_id: int
    reviewer_id: int
    reviewee_id: int
    rating: int
    comment: Optional[str] = None
    reviewer_name: str
    created_at: datetime
    updated_at: datetime


class PublicSellerReviewItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rating: int
    comment: Optional[str] = None
    verified_transaction: bool = True
    created_at: datetime
    updated_at: datetime


class PublicSellerReviewsCursorPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[PublicSellerReviewItem]
    next_cursor: Optional[str] = None
    has_more: bool
