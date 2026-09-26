from datetime import datetime
from typing import Optional

from app.modules.users.models import User

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Tutorial(Base):
    __tablename__ = "tutorials"

    tutorial_id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=False, start=1), primary_key=True
    )
    feature_key: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Video media (Cloudinary)
    video_url: Mapped[str] = mapped_column(String(500), nullable=False)
    video_storage_key: Mapped[str] = mapped_column(String(255), nullable=False)
    video_mime_type: Mapped[str] = mapped_column(String(50), nullable=False)
    video_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    duration_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    # Derived thumbnail property from video delivery transformation
    @property
    def thumbnail_url(self) -> Optional[str]:
        if not self.video_storage_key:
            return None
        from app.integrations.cloudinary import build_tutorial_thumbnail_url
        return build_tutorial_thumbnail_url(self.video_storage_key, self.duration_ms)

    # Controlled action target (Optional)
    action_key: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Display & publish management
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    is_published: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("FALSE")
    )

    # Metadata & Auditing
    created_by: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.user_id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    creator: Mapped["User"] = relationship("User", foreign_keys=[created_by])

    __table_args__ = (
        CheckConstraint(
            "video_size_bytes > 0",
            name="chk_tutorials_video_size_pos",
        ),
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms > 0",
            name="chk_tutorials_duration_pos",
        ),
        CheckConstraint(
            "sort_order >= 0",
            name="chk_tutorials_sort_order_nonneg",
        ),
        Index(
            "ix_tutorials_pub_feature_sort",
            "is_published",
            "feature_key",
            "sort_order",
            "tutorial_id",
        ),
        Index(
            "ix_tutorials_created_by",
            "created_by",
        ),
    )
