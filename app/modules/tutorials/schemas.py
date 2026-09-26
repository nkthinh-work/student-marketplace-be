from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

ALLOWED_FEATURE_KEYS = {
    "HOME",
    "FAVORITES",
    "CREATE_PRODUCT",
    "MY_LISTINGS",
    "BUYER_ORDERS",
    "SELLER_ORDERS",
    "NOTIFICATIONS",
    "MESSAGES",
    "PROFILE",
    "FEEDBACK",
}

ALLOWED_ACTION_KEYS = {
    "HOME",
    "CREATE_PRODUCT",
    "MY_LISTINGS",
    "FAVORITES",
    "BUYER_ORDERS",
    "SELLER_ORDERS",
    "MESSAGES",
    "NOTIFICATIONS",
    "FEEDBACK",
    "PROFILE",
}


class PublicTutorialResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tutorial_id: int
    feature_key: str
    title: str
    description: Optional[str] = None
    video_url: str
    thumbnail_url: Optional[str] = None
    duration_ms: Optional[int] = None
    action_key: Optional[str] = None
    sort_order: int


class AdminTutorialResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tutorial_id: int
    feature_key: str
    title: str
    description: Optional[str] = None
    video_url: str
    video_storage_key: str
    video_mime_type: str
    video_size_bytes: int
    duration_ms: Optional[int] = None
    thumbnail_url: Optional[str] = None
    action_key: Optional[str] = None
    sort_order: int
    is_published: bool
    created_by: int
    created_at: datetime
    updated_at: datetime


class AdminTutorialUpdate(BaseModel):
    feature_key: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    action_key: Optional[str] = None
    is_published: Optional[bool] = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v_trimmed = v.strip()
            if not v_trimmed:
                raise ValueError("Tiêu đề không được để trống")
            if len(v_trimmed) > 120:
                raise ValueError("Tiêu đề không được vượt quá 120 ký tự")
            return v_trimmed
        return v

    @field_validator("feature_key")
    @classmethod
    def validate_feature_key(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v_trimmed = v.strip()
            if v_trimmed not in ALLOWED_FEATURE_KEYS:
                raise ValueError(
                    f"Tính năng '{v_trimmed}' không hợp lệ. Cho phép: {', '.join(sorted(ALLOWED_FEATURE_KEYS))}"
                )
            return v_trimmed
        return v

    @field_validator("action_key")
    @classmethod
    def validate_action_key(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v_trimmed = v.strip()
            if not v_trimmed:
                return None
            if v_trimmed not in ALLOWED_ACTION_KEYS:
                raise ValueError(
                    f"Hành động '{v_trimmed}' không hợp lệ. Cho phép: {', '.join(sorted(ALLOWED_ACTION_KEYS))}"
                )
            return v_trimmed
        return v

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v_trimmed = v.strip()
            if len(v_trimmed) > 500:
                raise ValueError("Mô tả không được vượt quá 500 ký tự")
            return v_trimmed if v_trimmed else None
        return v


class AdminTutorialReorderRequest(BaseModel):
    feature_key: str
    tutorial_ids: list[int] = Field(..., min_length=1)

    @field_validator("feature_key")
    @classmethod
    def validate_feature_key(cls, v: str) -> str:
        v_trimmed = v.strip()
        if v_trimmed not in ALLOWED_FEATURE_KEYS:
            raise ValueError(
                f"Tính năng '{v_trimmed}' không hợp lệ. Cho phép: {', '.join(sorted(ALLOWED_FEATURE_KEYS))}"
            )
        return v_trimmed

    @field_validator("tutorial_ids")
    @classmethod
    def validate_tutorial_ids(cls, v: list[int]) -> list[int]:
        if len(v) != len(set(v)):
            raise ValueError("Danh sách tutorial_ids không được chứa ID trùng lặp")
        return v
