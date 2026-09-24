from datetime import datetime
from typing import Optional, TYPE_CHECKING
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

if TYPE_CHECKING:
    from app.modules.orders.models import Order
    from app.modules.users.models import User


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        CheckConstraint("rating >= 1 AND rating <= 5", name="chk_reviews_rating"),
        CheckConstraint("reviewer_id <> reviewee_id", name="chk_reviews_reviewer_not_reviewee"),
        UniqueConstraint("order_id", "reviewer_id", name="ux_reviews_order_reviewer"),
        Index(
            "ix_reviews_reviewee_created_desc",
            "reviewee_id",
            text("created_at DESC"),
            text("review_id DESC"),
        ),
    )

    review_id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=False, start=1),
        primary_key=True,
    )
    order_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("orders.order_id", ondelete="RESTRICT"),
        nullable=False,
    )
    reviewer_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.user_id", ondelete="RESTRICT"),
        nullable=False,
    )
    reviewee_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.user_id", ondelete="RESTRICT"),
        nullable=False,
    )
    rating: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
    )
    comment: Mapped[Optional[str]] = mapped_column(
        String(1000),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    order: Mapped["Order"] = relationship("Order", lazy="select")
    reviewer: Mapped["User"] = relationship("User", foreign_keys=[reviewer_id], lazy="select")
    reviewee: Mapped["User"] = relationship("User", foreign_keys=[reviewee_id], lazy="select")
