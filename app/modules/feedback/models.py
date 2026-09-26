from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SiteFeedback(Base):
    __tablename__ = "site_feedback"

    feedback_id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=False, start=1), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        nullable=False,
    )

    user = relationship("User", foreign_keys=[user_id])
    attachments: Mapped[List["SiteFeedbackAttachment"]] = relationship(
        "SiteFeedbackAttachment",
        back_populates="feedback",
        cascade="all, delete-orphan",
        order_by="SiteFeedbackAttachment.attachment_id",
    )

    __table_args__ = (
        Index(
            "idx_site_feedback_created_at",
            text("created_at DESC"),
            text("feedback_id DESC"),
        ),
        Index(
            "idx_site_feedback_user_created",
            "user_id",
            text("created_at DESC"),
            text("feedback_id DESC"),
        ),
    )


class SiteFeedbackAttachment(Base):
    __tablename__ = "site_feedback_attachments"

    attachment_id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=False, start=1), primary_key=True
    )
    feedback_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("site_feedback.feedback_id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    media_url: Mapped[str] = mapped_column(String(500), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(50), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    duration_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    feedback: Mapped["SiteFeedback"] = relationship(
        "SiteFeedback", back_populates="attachments"
    )

    __table_args__ = (
        CheckConstraint(
            "kind IN ('IMAGE', 'VIDEO')",
            name="chk_site_feedback_attachments_kind",
        ),
        CheckConstraint(
            "size_bytes > 0",
            name="chk_site_feedback_attachments_size_bytes",
        ),
        Index(
            "idx_site_feedback_attachments_feedback_id",
            "feedback_id",
        ),
    )


class SupportContribution(Base):
    __tablename__ = "support_contributions"

    contribution_id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=False, start=1), primary_key=True
    )
    supporter_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.user_id", ondelete="RESTRICT"),
        nullable=False,
    )
    amount_vnd: Mapped[int] = mapped_column(BigInteger, nullable=False)
    is_public: Mapped[bool] = mapped_column(
        Boolean, server_default=text("FALSE"), default=False, nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    recorded_by: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.user_id", ondelete="RESTRICT"),
        nullable=False,
    )
    transaction_ref: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    admin_note: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    supporter = relationship("User", foreign_keys=[supporter_id])
    recorder = relationship("User", foreign_keys=[recorded_by])

    __table_args__ = (
        CheckConstraint("amount_vnd > 0", name="chk_support_contributions_amount_positive"),
        Index("ix_support_contributions_received_desc", text("received_at DESC"), text("contribution_id DESC")),
        Index("ix_support_contributions_public_supporter", "is_public", "supporter_id"),
        Index("ix_support_contributions_supporter_id", "supporter_id"),
        Index("ix_support_contributions_recorded_by", "recorded_by"),
    )


class SupportClaimStatus:
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class SupportClaim(Base):
    __tablename__ = "support_claims"

    claim_id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=False, start=1), primary_key=True
    )
    supporter_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.user_id", ondelete="RESTRICT"),
        nullable=False,
    )
    claimed_amount_vnd: Mapped[int] = mapped_column(BigInteger, nullable=False)
    claimed_transferred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    sender_account_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    wants_public: Mapped[bool] = mapped_column(
        Boolean, server_default=text("FALSE"), default=False, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20),
        server_default=text("'PENDING'"),
        default=SupportClaimStatus.PENDING,
        nullable=False,
    )
    reviewed_by: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    contribution_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("support_contributions.contribution_id", ondelete="SET NULL"),
        nullable=True,
    )
    rejection_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    supporter = relationship("User", foreign_keys=[supporter_id])
    reviewer = relationship("User", foreign_keys=[reviewed_by])
    contribution = relationship("SupportContribution", foreign_keys=[contribution_id])

    __table_args__ = (
        CheckConstraint("claimed_amount_vnd > 0", name="chk_support_claims_claimed_amount_positive"),
        CheckConstraint(
            "status IN ('PENDING', 'VERIFIED', 'REJECTED')",
            name="chk_support_claims_status",
        ),
        Index("ix_support_claims_status_created", "status", text("created_at DESC"), text("claim_id DESC")),
        Index("ix_support_claims_supporter", "supporter_id", text("created_at DESC"), text("claim_id DESC")),
        Index("ix_support_claims_reviewed_by", "reviewed_by"),
        Index("ix_support_claims_contribution_id", "contribution_id"),
    )
