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


# ======================================================================
# SUPPORTER LEADERBOARD & ADMIN SUPPORT CONTRIBUTIONS
# ======================================================================

class SupporterPublicIdentity(BaseModel):
    user_id: int
    full_name: str
    avatar_url: Optional[str] = None
    profile_path: str


class SupporterLeaderboardItem(BaseModel):
    rank: int
    supporter: SupporterPublicIdentity
    total_amount_vnd: int
    contribution_count: int
    last_supported_at: datetime


class SupporterLeaderboardResponse(BaseModel):
    items: List[SupporterLeaderboardItem]


class AdminUserSafeIdentity(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    full_name: str
    avatar_url: Optional[str] = None


class SupporterResolveResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    full_name: str
    avatar_url: Optional[str] = None
    profile_path: str


class AdminSupportContributionCreate(BaseModel):
    supporter_id: int
    amount_vnd: int = Field(..., gt=0, le=1_000_000_000, description="Số tiền ủng hộ (VND) lớn hơn 0")
    received_at: datetime
    is_public: bool = False
    transaction_ref: Optional[str] = Field(None, max_length=100)
    admin_note: Optional[str] = Field(None, max_length=255)

    @field_validator("transaction_ref", "admin_note", mode="before")
    @classmethod
    def trim_text(cls, v: Optional[str]) -> Optional[str]:
        if isinstance(v, str):
            trimmed = v.strip()
            return trimmed if trimmed else None
        return v


class AdminSupportContributionVisibilityUpdate(BaseModel):
    is_public: bool


class AdminSupportContributionItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    contribution_id: int
    supporter: AdminUserSafeIdentity
    amount_vnd: int
    is_public: bool
    received_at: datetime
    transaction_ref: Optional[str] = None
    admin_note: Optional[str] = None
    recorded_by: AdminUserSafeIdentity
    created_at: datetime


class AdminSupportContributionCursorPage(BaseModel):
    items: List[AdminSupportContributionItem]
    next_cursor: Optional[str] = None
    has_more: bool = False


# ======================================================================
# SUPPORT CLAIMS SCHEMAS (USER DECLARATION & ADMIN RECONCILIATION)
# ======================================================================

class SupportClaimCreate(BaseModel):
    claimed_amount_vnd: int = Field(..., gt=0, le=1_000_000_000, description="Số tiền đã chuyển (VND) lớn hơn 0")
    claimed_transferred_at: datetime
    sender_account_name: str = Field(..., min_length=1, max_length=120, description="Tên chủ tài khoản chuyển tiền")
    wants_public: bool = False

    @field_validator("sender_account_name", mode="before")
    @classmethod
    def validate_sender_name(cls, v: object) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("Tên chủ tài khoản chuyển tiền không được để trống")
        return v.strip()


class SupportClaimUserItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    claim_id: int
    claimed_amount_vnd: int
    claimed_transferred_at: datetime
    sender_account_name: Optional[str] = None
    wants_public: bool
    status: str
    created_at: datetime


class SupportClaimUserListPage(BaseModel):
    items: List[SupportClaimUserItem]


class AdminSupportClaimVerify(BaseModel):
    amount_vnd: int = Field(..., gt=0, le=1_000_000_000, description="Số tiền thực nhận (VND) lớn hơn 0")
    received_at: datetime
    transaction_ref: Optional[str] = Field(None, max_length=100)
    admin_note: Optional[str] = Field(None, max_length=255)

    @field_validator("transaction_ref", "admin_note", mode="before")
    @classmethod
    def trim_text(cls, v: Optional[str]) -> Optional[str]:
        if isinstance(v, str):
            trimmed = v.strip()
            return trimmed if trimmed else None
        return v


class AdminSupportClaimReject(BaseModel):
    rejection_reason: Optional[str] = Field(None, max_length=255)

    @field_validator("rejection_reason", mode="before")
    @classmethod
    def trim_reason(cls, v: Optional[str]) -> Optional[str]:
        if isinstance(v, str):
            trimmed = v.strip()
            return trimmed if trimmed else None
        return v


class AdminSupportClaimItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    claim_id: int
    supporter: SupporterResolveResponse
    claimed_amount_vnd: int
    claimed_transferred_at: datetime
    sender_account_name: Optional[str] = None
    wants_public: bool
    status: str
    reviewed_by: Optional[AdminUserSafeIdentity] = None
    reviewed_at: Optional[datetime] = None
    contribution_id: Optional[int] = None
    rejection_reason: Optional[str] = None
    created_at: datetime


class AdminSupportClaimCursorPage(BaseModel):
    items: List[AdminSupportClaimItem]
    next_cursor: Optional[str] = None
    has_more: bool = False
