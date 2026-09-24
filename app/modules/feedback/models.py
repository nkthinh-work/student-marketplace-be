from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy import (
    BigInteger,
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
