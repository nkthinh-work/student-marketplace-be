from datetime import datetime
from enum import Enum
from typing import Optional, Any
from urllib.parse import urlparse
from pydantic import BaseModel, ConfigDict, Field, field_validator, ValidationInfo

from app.core.banks import BankInfo, get_bank_by_bin, resolve_bank_bin


class SocialPlatform(str, Enum):
    FACEBOOK = "FACEBOOK"
    INSTAGRAM = "INSTAGRAM"
    TIKTOK = "TIKTOK"
    ZALO = "ZALO"
    LINKEDIN = "LINKEDIN"


class SocialLinkItem(BaseModel):
    platform: SocialPlatform
    url: str

    @field_validator("url", mode="after")
    @classmethod
    def validate_social_url(cls, v: str, info: ValidationInfo) -> str:
        v = v.strip()
        if not v:
            raise ValueError("URL không được để trống.")
        if not (v.startswith("https://") or v.startswith("http://")):
            raise ValueError("URL phải bắt đầu bằng https:// hoặc http://.")
        
        parsed = urlparse(v)
        hostname = (parsed.hostname or "").lower()
        if not hostname:
            raise ValueError("Định dạng URL không hợp lệ.")
        
        platform = info.data.get("platform")
        if platform == SocialPlatform.FACEBOOK:
            valid = hostname in ("facebook.com", "www.facebook.com", "m.facebook.com", "fb.com", "www.fb.com")
            if not valid:
                raise ValueError("Liên kết không thuộc Facebook.")
        elif platform == SocialPlatform.INSTAGRAM:
            valid = hostname in ("instagram.com", "www.instagram.com", "instagr.am")
            if not valid:
                raise ValueError("Liên kết không thuộc Instagram.")
        elif platform == SocialPlatform.TIKTOK:
            valid = hostname in ("tiktok.com", "www.tiktok.com", "vt.tiktok.com")
            if not valid:
                raise ValueError("Liên kết không thuộc TikTok.")
        elif platform == SocialPlatform.ZALO:
            valid = hostname in ("zalo.me", "chat.zalo.me")
            if not valid:
                raise ValueError("Liên kết không thuộc Zalo.")
        elif platform == SocialPlatform.LINKEDIN:
            valid = hostname in ("linkedin.com", "www.linkedin.com", "vn.linkedin.com")
            if not valid:
                raise ValueError("Liên kết không thuộc LinkedIn.")
        
        return v


class UserResponse(BaseModel):
    user_id: int
    email: str
    full_name: str
    phone: Optional[str] = None
    show_phone_publicly: bool = False
    social_links: Optional[list[SocialLinkItem]] = None
    avatar_url: Optional[str] = None
    bio: Optional[str] = None
    delivery_area: Optional[str] = None
    default_meetup_area: Optional[str] = None
    role: str
    status: str
    last_active_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PublicUserProfileResponse(BaseModel):
    user_id: int
    full_name: str
    avatar_url: Optional[str] = None
    bio: Optional[str] = None
    delivery_area: Optional[str] = None
    phone: Optional[str] = None
    social_links: Optional[list[SocialLinkItem]] = None
    role: str
    created_at: datetime
    active_listing_count: int = 0
    completed_sold_count: int = 0

    model_config = ConfigDict(from_attributes=True, extra="forbid")


class SoldProductSummary(BaseModel):
    product_id: int
    product_title: str
    product_image_url: Optional[str] = None
    total_sold_quantity: int
    last_sold_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True, extra="forbid")


class SoldProductListResponse(BaseModel):
    items: list[SoldProductSummary]
    total_count: int

    model_config = ConfigDict(extra="forbid")


class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(None, min_length=1, max_length=100)
    phone: Optional[str] = Field(None, max_length=20)
    show_phone_publicly: Optional[bool] = None
    social_links: Optional[list[SocialLinkItem]] = None
    bio: Optional[str] = Field(None, max_length=500)
    delivery_area: Optional[str] = Field(None, max_length=255)
    default_meetup_area: Optional[str] = Field(None, max_length=255)

    model_config = ConfigDict(extra="forbid")


class BankAccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    bank_bin: str
    bank_code: str
    bank_name: str
    bank_short_name: str
    account_number: str
    account_name: str


class BankAccountUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bank_bin: str = Field(..., min_length=2, max_length=20)
    account_number: str = Field(..., min_length=4, max_length=30)
    account_name: str = Field(..., min_length=2, max_length=100)

    @field_validator("bank_bin", mode="after")
    @classmethod
    def validate_bank_bin(cls, v: str) -> str:
        v = v.strip()
        resolved = resolve_bank_bin(v)
        if not resolved:
            raise ValueError("Mã ngân hàng (BIN/Code) không hợp lệ hoặc không được hỗ trợ.")
        return resolved

    @field_validator("account_number", mode="after")
    @classmethod
    def validate_account_number(cls, v: str) -> str:
        v = v.strip()
        if not v.isalnum():
            raise ValueError("Số tài khoản chỉ được chứa chữ cái và chữ số, không chứa khoảng trắng hoặc ký tự đặc biệt.")
        if len(v) < 4 or len(v) > 30:
            raise ValueError("Độ dài số tài khoản không hợp lệ (4 - 30 ký tự).")
        return v

    @field_validator("account_name", mode="after")
    @classmethod
    def validate_account_name(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 2 or len(v) > 100:
            raise ValueError("Tên chủ tài khoản phải từ 2 đến 100 ký tự.")
        return v
