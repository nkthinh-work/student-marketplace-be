from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    notification_id: int
    type: str
    title: str
    body: Optional[str] = None
    ref_type: Optional[str] = None
    ref_id: Optional[int] = None
    is_read: bool
    created_at: datetime


class NotificationListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    items: list[NotificationResponse]
    next_cursor: Optional[str] = None
    has_more: bool


class UnreadCountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    count: int


class PushSubscribeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fcm_token: str
    device_info: Optional[str] = None


class PushUnsubscribeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fcm_token: str


class PushSubscriptionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
