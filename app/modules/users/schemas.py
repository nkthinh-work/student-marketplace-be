from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


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
    avatar_url: Optional[str] = Field(None, max_length=500)
    bio: Optional[str] = Field(None, max_length=500)
    default_meetup_area: Optional[str] = Field(None, max_length=255)

    model_config = ConfigDict(extra="forbid")
