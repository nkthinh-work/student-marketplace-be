import uuid
from datetime import datetime, date
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class DailyNeedAuthor(BaseModel):
    public_id: uuid.UUID
    full_name: str
    avatar_url: Optional[str] = None

    model_config = ConfigDict(from_attributes=True, extra="forbid")



class DailyNeedResponse(BaseModel):
    daily_need_id: int
    content: str
    note_date: date
    created_at: datetime
    updated_at: datetime
    author: DailyNeedAuthor
    checkin_created: bool = False

    model_config = ConfigDict(from_attributes=True, extra="forbid")


class DailyNeedPublicResponse(BaseModel):
    daily_need_id: int
    content: str
    note_date: date
    updated_at: datetime
    author: Optional[DailyNeedAuthor] = None

    model_config = ConfigDict(from_attributes=True, extra="forbid")


class DailyNeedSummaryResponse(BaseModel):
    today_journal: Optional[DailyNeedResponse] = None
    has_journal_today: bool
    has_checked_in_today: bool
    has_posted_today: bool  # Deprecated: equals has_checked_in_today for backwards compatibility
    streak_count: int

    model_config = ConfigDict(extra="forbid")



class DailyNeedCreateOrUpdate(BaseModel):
    content: str = Field(..., min_length=1, max_length=120)

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Nội dung nhật ký không được để trống.")
        # Normalize internal whitespace/newlines to single line
        v = " ".join(v.split())
        if len(v) > 120:
            raise ValueError("Nội dung nhật ký tối đa 120 ký tự.")
        return v

    model_config = ConfigDict(extra="forbid")


class DailyNeedListResponse(BaseModel):
    items: list[DailyNeedResponse]

    model_config = ConfigDict(extra="forbid")

