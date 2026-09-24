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
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.modules.reports.models import Report  # noqa: F401



class CapabilityType(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


class UserCapabilityRestriction(Base):
    __tablename__ = "user_capability_restrictions"
    __table_args__ = (
        CheckConstraint(
            "capability IN ('BUY', 'SELL')",
            name="chk_user_capability_restrictions_capability",
        ),
        CheckConstraint(
            "expires_at IS NULL OR expires_at > starts_at",
            name="chk_user_capability_restrictions_expires_at",
        ),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= starts_at",
            name="chk_user_capability_restrictions_revoked_at",
        ),
        Index(
            "ix_user_capability_restrictions_user_cap",
            "user_id",
            "capability",
        ),
        Index(
            "ix_user_capability_restrictions_source_report",
            "source_report_id",
        ),
        Index(
            "ix_user_capability_restrictions_active_lookup",
            "user_id",
            "capability",
            "starts_at",
            "expires_at",
            "revoked_at",
        ),
    )

    restriction_id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=False, start=1), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.user_id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_report_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("reports.report_id", ondelete="RESTRICT"),
        nullable=False,
    )
    imposed_by: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.user_id", ondelete="RESTRICT"),
        nullable=False,
    )
    capability: Mapped[str] = mapped_column(
        String(10), nullable=False
    )
    starts_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        nullable=False,
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    revoked_by: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        nullable=False,
    )

    # Relationships
    user = relationship("User", foreign_keys=[user_id], backref="capability_restrictions")
    source_report = relationship("Report", foreign_keys=[source_report_id], backref="imposed_capability_restrictions")
    imposing_admin = relationship("User", foreign_keys=[imposed_by])
    revoking_admin = relationship("User", foreign_keys=[revoked_by])

    def is_effective(self, now_utc: datetime) -> bool:
        """Determines if the restriction is active at the provided UTC timestamp."""
        if self.revoked_at is not None:
            return False
        if self.starts_at > now_utc:
            return False
        if self.expires_at is not None and self.expires_at <= now_utc:
            return False
        return True
