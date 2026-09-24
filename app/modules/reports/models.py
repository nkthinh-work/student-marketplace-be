import enum
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ReportTargetType(str, enum.Enum):
    USER = "USER"
    PRODUCT = "PRODUCT"
    ORDER = "ORDER"


class ReportReason(str, enum.Enum):
    SCAM = "SCAM"
    FAKE_ITEM = "FAKE_ITEM"
    SPAM = "SPAM"
    INAPPROPRIATE = "INAPPROPRIATE"
    NO_SHOW = "NO_SHOW"
    OTHER = "OTHER"


class ReportStatus(str, enum.Enum):
    OPEN = "OPEN"
    REVIEWING = "REVIEWING"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"


class ReportWorkflowState(str, enum.Enum):
    OPEN = "OPEN"
    REVIEWING = "REVIEWING"
    COMPLETED = "COMPLETED"


class AdminReportQueueState(str, enum.Enum):
    NEEDS_ACTION = "NEEDS_ACTION"
    COMPLETED = "COMPLETED"


class ReportConclusion(str, enum.Enum):
    SUPPORTED = "SUPPORTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class ModerationActionOption(str, enum.Enum):
    START_REVIEW = "START_REVIEW"
    CONFIRM_SUPPORTED = "CONFIRM_SUPPORTED"
    MARK_INSUFFICIENT_EVIDENCE = "MARK_INSUFFICIENT_EVIDENCE"



REPORT_REASON_MATRIX: dict[ReportTargetType, set[ReportReason]] = {
    ReportTargetType.USER: {
        ReportReason.SCAM,
        ReportReason.SPAM,
        ReportReason.INAPPROPRIATE,
        ReportReason.OTHER,
    },
    ReportTargetType.PRODUCT: {
        ReportReason.SCAM,
        ReportReason.FAKE_ITEM,
        ReportReason.SPAM,
        ReportReason.INAPPROPRIATE,
        ReportReason.OTHER,
    },
    ReportTargetType.ORDER: {
        ReportReason.SCAM,
        ReportReason.FAKE_ITEM,
        ReportReason.SPAM,
        ReportReason.INAPPROPRIATE,
        ReportReason.NO_SHOW,
        ReportReason.OTHER,
    },
}


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (
        CheckConstraint(
            "target_type IN ('USER', 'PRODUCT', 'ORDER')",
            name="ck_reports_target_type",
        ),
        CheckConstraint(
            "reason IN ('SCAM', 'FAKE_ITEM', 'SPAM', 'INAPPROPRIATE', 'NO_SHOW', 'OTHER')",
            name="ck_reports_reason",
        ),
        CheckConstraint(
            "status IN ('OPEN', 'REVIEWING', 'RESOLVED', 'REJECTED')",
            name="ck_reports_status",
        ),
        Index(
            "ix_reports_status_created_desc",
            "status",
            text("created_at DESC"),
            text("report_id DESC"),
        ),
        Index(
            "ix_reports_reporter_target",
            "reporter_id",
            "target_type",
            "target_id",
        ),
    )

    report_id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=False, start=1), primary_key=True
    )
    reporter_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    target_type: Mapped[str] = mapped_column(
        String(10), nullable=False
    )
    target_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False
    )
    reason: Mapped[str] = mapped_column(
        String(20), nullable=False
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(10), server_default="OPEN", default=ReportStatus.OPEN.value, nullable=False
    )
    handled_by: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    handled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        nullable=False,
    )

    reporter = relationship("User", foreign_keys=[reporter_id])
    handler = relationship("User", foreign_keys=[handled_by])
    attachments = relationship(
        "ReportAttachment",
        back_populates="report",
        cascade="all, delete-orphan",
        order_by="ReportAttachment.attachment_id.asc()",
    )
    moderation_actions = relationship(
        "ModerationAction",
        back_populates="report",
        order_by="[ModerationAction.created_at.asc(), ModerationAction.moderation_action_id.asc()]",
    )


class ReportAttachment(Base):
    __tablename__ = "report_attachments"

    attachment_id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=False, start=1), primary_key=True
    )
    report_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("reports.report_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        nullable=False,
    )

    report = relationship("Report", back_populates="attachments")

    @property
    def media_type(self) -> str:
        if self.mime_type and self.mime_type.startswith("video/"):
            return "VIDEO"
        return "IMAGE"


class ModerationActionType(str, enum.Enum):
    USER_BAN = "USER_BAN"
    USER_UNBAN = "USER_UNBAN"
    PRODUCT_HIDE = "PRODUCT_HIDE"
    PRODUCT_RESTORE = "PRODUCT_RESTORE"
    BUY_RESTRICT = "BUY_RESTRICT"
    BUY_RESTORE = "BUY_RESTORE"
    SELL_RESTRICT = "SELL_RESTRICT"
    SELL_RESTORE = "SELL_RESTORE"


class ModerationAction(Base):
    __tablename__ = "moderation_actions"
    __table_args__ = (
        CheckConstraint(
            "target_type IN ('USER', 'PRODUCT')",
            name="chk_moderation_actions_target_type",
        ),
        CheckConstraint(
            "action_type IN ('USER_BAN', 'USER_UNBAN', 'PRODUCT_HIDE', 'PRODUCT_RESTORE', 'BUY_RESTRICT', 'BUY_RESTORE', 'SELL_RESTRICT', 'SELL_RESTORE')",
            name="chk_moderation_actions_action_type",
        ),
        Index(
            "ix_moderation_actions_report_history",
            "report_id",
            "created_at",
            "moderation_action_id",
        ),
        Index(
            "ix_moderation_actions_target_history",
            "target_type",
            "target_id",
            "created_at",
            "moderation_action_id",
        ),
    )

    moderation_action_id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=False, start=1), primary_key=True
    )
    report_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("reports.report_id", ondelete="RESTRICT"),
        nullable=False,
    )
    admin_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.user_id", ondelete="RESTRICT"),
        nullable=False,
    )
    target_type: Mapped[str] = mapped_column(
        String(10), nullable=False
    )
    target_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False
    )
    action_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )
    previous_status: Mapped[str] = mapped_column(
        String(20), nullable=False
    )
    new_status: Mapped[str] = mapped_column(
        String(20), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        nullable=False,
    )

    report = relationship("Report", back_populates="moderation_actions")
    admin = relationship("User", foreign_keys=[admin_id])
