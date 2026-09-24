import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class NotificationType(str, enum.Enum):
    NEW_ORDER = "NEW_ORDER"
    ORDER_STATUS = "ORDER_STATUS"
    NEW_MESSAGE = "NEW_MESSAGE"
    NEW_REVIEW = "NEW_REVIEW"
    AUCTION_BID = "AUCTION_BID"
    AUCTION_OUTBID = "AUCTION_OUTBID"
    AUCTION_WON = "AUCTION_WON"
    AUCTION_ENDED = "AUCTION_ENDED"
    SYSTEM = "SYSTEM"


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint(
            "type IN ('NEW_ORDER','ORDER_STATUS','NEW_MESSAGE','NEW_REVIEW',"
            "'AUCTION_BID','AUCTION_OUTBID','AUCTION_WON','AUCTION_ENDED','SYSTEM')",
            name="chk_notifications_type",
        ),
        Index(
            "ix_notifications_user_read_created",
            "user_id",
            "is_read",
            "created_at",
        ),
    )

    notification_id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=False, start=1), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )
    title: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    body: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    ref_type: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )
    ref_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    is_read: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    user = relationship("User", foreign_keys=[user_id])
