import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.products.models import ProductModerationStatus
from app.modules.reports.models import (
    REPORT_REASON_MATRIX,
    AdminReportQueueState,
    ModerationActionOption,
    ModerationActionType,
    ReportConclusion,
    ReportReason,
    ReportStatus,
    ReportTargetType,
    ReportWorkflowState,
)


class ReportCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_type: ReportTargetType
    target_id: Optional[int] = Field(None, gt=0, description="ID của đối tượng bị báo cáo")
    target_public_id: Optional[uuid.UUID] = Field(None, description="Public UUID của người dùng bị báo cáo")
    reason: ReportReason
    description: Optional[str] = Field(
        None, max_length=1000, description="Mô tả chi tiết lý do báo cáo (tối đa 1000 ký tự)"
    )

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        trimmed = v.strip()
        return trimmed if trimmed else None

    @model_validator(mode="after")
    def validate_reason_and_description(self) -> "ReportCreateRequest":
        if self.target_type == ReportTargetType.USER:
            if self.target_id is not None:
                raise ValueError("Báo cáo người dùng chỉ chấp nhận target_public_id (UUID), không chấp nhận target_id số nguyên.")
            if self.target_public_id is None:
                raise ValueError("target_public_id là bắt buộc khi báo cáo người dùng.")
        else:
            if self.target_public_id is not None:
                raise ValueError("target_public_id chỉ áp dụng cho báo cáo người dùng.")
            if self.target_id is None:
                raise ValueError("target_id là bắt buộc đối với báo cáo sản phẩm hoặc đơn hàng.")

        allowed_reasons = REPORT_REASON_MATRIX.get(self.target_type, set())
        if self.reason not in allowed_reasons:
            raise ValueError(
                f"Lý do báo cáo '{self.reason.value}' không phù hợp với loại đối tượng '{self.target_type.value}'."
            )

        if self.reason == ReportReason.OTHER and not self.description:
            raise ValueError("Mô tả chi tiết là bắt buộc khi chọn lý do 'Khác'.")

        return self


class ReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    report_id: int
    target_type: ReportTargetType
    target_id: int
    reason: ReportReason
    description: Optional[str]
    status: ReportStatus
    created_at: datetime


class ReporterSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    full_name: str
    avatar_url: Optional[str] = None


class AdminHandlerSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    full_name: str


class UserTargetSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    full_name: str
    avatar_url: Optional[str] = None
    status: str
    role: Optional[str] = None


class ProductTargetSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_id: int
    title: str
    seller: Optional[AdminHandlerSummary] = None
    status: str
    moderation_status: ProductModerationStatus
    is_deleted: bool


class OrderTargetSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    order_id: int
    order_code: str
    buyer: Optional[AdminHandlerSummary] = None
    seller: Optional[AdminHandlerSummary] = None
    status: str
    total_amount: Optional[int] = None


class AdminReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    report_id: int
    reporter_id: int
    reporter: Optional[ReporterSummary] = None
    target_type: ReportTargetType
    target_id: int
    target_available: bool = True
    target_summary: Optional[
        UserTargetSummary | ProductTargetSummary | OrderTargetSummary | dict[str, Any]
    ] = None
    reason: ReportReason
    description: Optional[str] = None
    status: ReportStatus
    workflow_state: ReportWorkflowState
    conclusion: Optional[ReportConclusion] = None
    handled_by: Optional[int] = None
    handler: Optional[AdminHandlerSummary] = None
    handled_at: Optional[datetime] = None
    created_at: datetime
    evidence_count: int = 0


class ReportEvidenceMetadata(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    attachment_id: int
    original_name: str
    mime_type: str
    size_bytes: int
    created_at: datetime
    media_type: str = "IMAGE"


class ReportEvidenceUploadResponse(BaseModel):
    report_id: int
    attachments: list[ReportEvidenceMetadata] = Field(default_factory=list)


class ModerationActionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    moderation_action_id: int
    action_type: ModerationActionType
    previous_status: str
    new_status: str
    admin: Optional[AdminHandlerSummary] = None
    created_at: datetime


class AdminCapabilityRestrictionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    capability: str
    expires_at: Optional[datetime] = None
    restorable_from_current_report: bool = False


class ReportedSubjectSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    full_name: str
    avatar_url: Optional[str] = None
    role_in_order: Optional[str] = None
    status: str
    can_buy: bool
    can_sell: bool
    active_restrictions: list[AdminCapabilityRestrictionResponse] = Field(default_factory=list)
    prior_report_count: int = 0


class SubjectReportHistoryEnforcementAction(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    action_type: ModerationActionType
    previous_status: str
    new_status: str


class SubjectReportHistoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    report_id: int
    target_type: ReportTargetType
    reason: ReportReason
    status: ReportStatus
    created_at: datetime
    handled_at: Optional[datetime] = None
    evidence_count: int = 0
    enforcement_actions: list[SubjectReportHistoryEnforcementAction] = Field(default_factory=list)


class SubjectReportHistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    items: list[SubjectReportHistoryItem]
    next_cursor: Optional[str] = None
    has_more: bool
    total_count: int



class AdminReportDetailResponse(AdminReportResponse):
    evidence: list[ReportEvidenceMetadata] = Field(default_factory=list)
    enforcement_actions: list[ModerationActionSummary] = Field(default_factory=list)
    available_moderation_actions: list[ModerationActionOption] = Field(default_factory=list)
    available_enforcement_actions: list[str] = Field(default_factory=list)
    reported_subject: Optional[ReportedSubjectSummary] = None


class AdminReportListResponse(BaseModel):
    items: list[AdminReportResponse]
    next_cursor: Optional[str] = None
    has_more: bool


class AdminReportStatusUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ReportStatus


class AdminEnforcementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str
    capabilities: Optional[list[str]] = None
    duration_days: Optional[int] = None

    @model_validator(mode="after")
    def validate_enforcement_request(self) -> "AdminEnforcementRequest":
        valid_actions = {
            "USER_BAN",
            "USER_UNBAN",
            "PRODUCT_HIDE",
            "PRODUCT_RESTORE",
            "CAPABILITY_RESTRICT",
            "CAPABILITY_RESTORE",
        }
        if self.action not in valid_actions:
            raise ValueError(f"Hành động chế tài '{self.action}' không hợp lệ.")

        if self.action == "CAPABILITY_RESTRICT":
            if not self.capabilities:
                raise ValueError("capabilities là bắt buộc đối với CAPABILITY_RESTRICT.")
            valid_caps = {"BUY", "SELL"}
            if not set(self.capabilities).issubset(valid_caps) or len(self.capabilities) == 0:
                raise ValueError("capabilities phải là danh sách không rỗng chứa 'BUY' và/hoặc 'SELL'.")
            if len(self.capabilities) != len(set(self.capabilities)):
                raise ValueError("capabilities không được chứa phần tử trùng lặp.")
            if "duration_days" not in self.model_fields_set or self.duration_days is None:
                raise ValueError("duration_days là bắt buộc đối với CAPABILITY_RESTRICT (chọn 1, 3, 7 hoặc 14 ngày).")
            if self.duration_days not in (1, 3, 7, 14):
                raise ValueError("duration_days chỉ chấp nhận 1, 3, 7 hoặc 14 ngày.")

        elif self.action == "CAPABILITY_RESTORE":
            if not self.capabilities:
                raise ValueError("capabilities là bắt buộc đối với CAPABILITY_RESTORE.")
            valid_caps = {"BUY", "SELL"}
            if not set(self.capabilities).issubset(valid_caps) or len(self.capabilities) == 0:
                raise ValueError("capabilities phải là danh sách không rỗng chứa 'BUY' và/hoặc 'SELL'.")
            if len(self.capabilities) != len(set(self.capabilities)):
                raise ValueError("capabilities không được chứa phần tử trùng lặp.")
            if "duration_days" in self.model_fields_set:
                raise ValueError("duration_days không được cung cấp đối với CAPABILITY_RESTORE.")

        else:
            if "capabilities" in self.model_fields_set and self.capabilities is not None:
                raise ValueError(f"capabilities không áp dụng cho hành động '{self.action}'.")
            if "duration_days" in self.model_fields_set:
                raise ValueError(f"duration_days không áp dụng cho hành động '{self.action}'.")

        return self

