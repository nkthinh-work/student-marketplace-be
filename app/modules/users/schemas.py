from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.banks import BankInfo, get_bank_by_bin, resolve_bank_bin


class UserResponse(BaseModel):
    user_id: int
    email: str
    full_name: str
    phone: Optional[str] = None
    avatar_url: Optional[str] = None
    bio: Optional[str] = None
    default_meetup_area: Optional[str] = None
    role: str
    status: str
    last_active_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(None, min_length=1, max_length=100)
    phone: Optional[str] = Field(None, max_length=20)
    bio: Optional[str] = Field(None, max_length=500)
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
