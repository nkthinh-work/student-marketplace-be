from datetime import datetime, date
from sqlalchemy import (
    BigInteger,
    String,
    Date,
    DateTime,
    ForeignKey,
    Index,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


class DailyNeed(Base):
    __tablename__ = "daily_needs"
    __table_args__ = (
        UniqueConstraint("user_id", "note_date", name="uq_daily_needs_user_date"),
        Index(
            "ix_daily_needs_today_recency",
            "note_date",
            "updated_at",
            "daily_need_id",
        ),
    )

    daily_need_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    note_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )
    content: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Eager joined relationship to ensure zero N+1 queries when loading public feed
    user = relationship("User", lazy="joined")


class DailyJournalCheckin(Base):
    __tablename__ = "daily_journal_checkins"
    __table_args__ = (
        UniqueConstraint("user_id", "checkin_date", name="uq_daily_journal_checkins_user_date"),
    )

    checkin_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    checkin_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    user = relationship("User")

