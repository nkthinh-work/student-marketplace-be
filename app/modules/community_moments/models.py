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
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CommunityMomentStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class CommunityMoment(Base):
    __tablename__ = "community_moments"

    moment_id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=False, start=1), primary_key=True
    )
    uploader_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.user_id", ondelete="RESTRICT"),
        nullable=False,
    )
    image_url: Mapped[str] = mapped_column(String(500), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    note: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        server_default="PENDING",
        default=CommunityMomentStatus.PENDING.value,
        nullable=False,
    )
    reviewed_by: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        nullable=False,
    )

    uploader = relationship("User", foreign_keys=[uploader_id])
    reviewer = relationship("User", foreign_keys=[reviewed_by])

    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'APPROVED', 'REJECTED')",
            name="chk_community_moments_status",
        ),
        CheckConstraint("size_bytes > 0", name="chk_community_moments_size_bytes"),
        Index(
            "uq_community_moments_user_pending",
            "uploader_id",
            unique=True,
            postgresql_where=text("status = 'PENDING'"),
        ),
        Index(
            "ix_community_moments_status_created",
            "status",
            "created_at",
            "moment_id",
        ),
        Index(
            "ix_community_moments_approved_hero",
            "status",
            "reviewed_at",
            "moment_id",
        ),
    )
