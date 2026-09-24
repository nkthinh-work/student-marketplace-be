import unicodedata
from datetime import datetime
from typing import List, Optional

from fastapi import HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator


def sanitize_feedback_content(v: str) -> str:
    if not isinstance(v, str):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Nội dung phản hồi phải là chuỗi ký tự.",
        )
    # Normalize NFC
    normalized = unicodedata.normalize("NFC", v)
    trimmed = normalized.strip()
    if len(trimmed) < 5:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Nội dung phản hồi phải có ít nhất 5 ký tự.",
        )
    if len(trimmed) > 500:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Nội dung phản hồi không được vượt quá 500 ký tự.",
        )
    # Reject non-printable or control characters except newline and carriage return
    for ch in trimmed:
        if ch in ("\r", "\n", "\t"):
            continue
        cat = unicodedata.category(ch)
        if cat.startswith("C"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Nội dung phản hồi chứa ký tự điều khiển không hợp lệ.",
            )
    return trimmed


class FeedbackAttachmentItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    attachment_id: int
    kind: str
    mime_type: str
    size_bytes: int
    duration_ms: Optional[int] = None


class FeedbackCreateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    feedback_id: int
    content: str
    created_at: datetime
    attachments: List[FeedbackAttachmentItem] = []


class PublicFeedbackItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    feedback_id: int
    content: str
    created_at: datetime


class PublicFeedbackCursorPage(BaseModel):
    items: List[PublicFeedbackItem]
    next_cursor: Optional[str] = None
    has_more: bool = False


class MyFeedbackItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    feedback_id: int
    content: str
    created_at: datetime
    attachments: List[FeedbackAttachmentItem] = []


class MyFeedbackCursorPage(BaseModel):
    items: List[MyFeedbackItem]
    next_cursor: Optional[str] = None
    has_more: bool = False


class AdminFeedbackSender(BaseModel):
    user_id: int
    full_name: str
    avatar_url: Optional[str] = None


class AdminFeedbackAttachmentItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    attachment_id: int
    kind: str
    mime_type: str
    size_bytes: int
    duration_ms: Optional[int] = None
    stream_url: str


class AdminFeedbackListItem(BaseModel):
    feedback_id: int
    sender: AdminFeedbackSender
    content: str
    created_at: datetime
    image_count: int
    video_count: int


class AdminFeedbackListPage(BaseModel):
    items: List[AdminFeedbackListItem]
    next_cursor: Optional[str] = None
    has_more: bool = False


class AdminFeedbackDetail(BaseModel):
    feedback_id: int
    sender: AdminFeedbackSender
    content: str
    created_at: datetime
    attachments: List[AdminFeedbackAttachmentItem] = []


class CreatorPublicInfo(BaseModel):
    user_id: int
    full_name: str
    avatar_url: Optional[str] = None
    title: str = "Người phát triển Chợ PTITers"


class SupportResponse(BaseModel):
    creator: Optional[CreatorPublicInfo] = None
    profile_path: Optional[str] = None
    fixed_qr_url: str = "/support/nguyen-khac-thinh-vietqr.png"
    support_message: str = "Quan trọng là tấm lòng 💛"
