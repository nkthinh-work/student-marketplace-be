from datetime import datetime
from decimal import Decimal
import enum
from typing import Optional, TYPE_CHECKING
from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    String,
    CheckConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

if TYPE_CHECKING:
    from app.modules.users.models import User
    from app.modules.products.models import Product


class AuctionStatus(str, enum.Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"
    CANCELLED = "CANCELLED"


class Auction(Base):
    __tablename__ = "auctions"
    __table_args__ = (
        CheckConstraint("bid_step > 0", name="chk_auctions_bid_step"),
        CheckConstraint("starting_price >= 0", name="chk_auctions_starting_price"),
        CheckConstraint("ends_at > starts_at", name="chk_auctions_time_window"),
        CheckConstraint(
            "status IN ('SCHEDULED', 'ACTIVE', 'ENDED', 'CANCELLED')",
            name="chk_auctions_status",
        ),
        CheckConstraint(
            "final_price IS NULL OR final_price >= starting_price",
            name="chk_auctions_final_price_gte_start",
        ),
        CheckConstraint(
            "status = 'ENDED' OR (winner_id IS NULL AND final_price IS NULL AND winner_checkout_deadline IS NULL)",
            name="chk_auctions_non_ended_no_winner",
        ),
        CheckConstraint(
            "(winner_id IS NULL AND final_price IS NULL AND winner_checkout_deadline IS NULL) OR "
            "(winner_id IS NOT NULL AND final_price IS NOT NULL AND final_price > 0 AND winner_checkout_deadline IS NOT NULL)",
            name="chk_auctions_winner_consistency",
        ),
        Index(
            "ux_auctions_product_active",
            "product_id",
            unique=True,
            postgresql_where=text("status IN ('SCHEDULED', 'ACTIVE')"),
        ),
        Index("ix_auctions_product_id", "product_id"),
        Index("ix_auctions_status_ends_at", "status", "ends_at"),
        Index("ix_auctions_status_starts_at", "status", "starts_at"),
        Index(
            "ix_auctions_winner_deadline",
            "status",
            "winner_checkout_deadline",
            postgresql_where=text("winner_id IS NOT NULL"),
        ),
    )

    auction_id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=False, start=1), primary_key=True
    )
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("products.product_id", ondelete="CASCADE"), nullable=False
    )
    starting_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 0), nullable=False
    )
    bid_step: Mapped[Decimal] = mapped_column(
        Numeric(12, 0), nullable=False
    )
    starts_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    ends_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default=AuctionStatus.SCHEDULED.value,
        server_default=AuctionStatus.SCHEDULED.value,
    )
    winner_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=True
    )
    final_price: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 0), nullable=True
    )
    winner_checkout_deadline: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    product: Mapped["Product"] = relationship("Product", lazy="selectin")
    winner: Mapped[Optional["User"]] = relationship("User", foreign_keys=[winner_id], lazy="selectin")
    bids: Mapped[list["AuctionBid"]] = relationship(
        "AuctionBid",
        back_populates="auction",
        cascade="all, delete-orphan",
        order_by="AuctionBid.amount.desc(), AuctionBid.created_at.asc(), AuctionBid.bid_id.asc()",
        lazy="selectin",
    )


class AuctionBid(Base):
    __tablename__ = "auction_bids"
    __table_args__ = (
        CheckConstraint("amount > 0", name="chk_auction_bids_amount"),
        Index(
            "ix_auction_bids_auction_amount_created",
            "auction_id",
            text("amount DESC"),
            text("created_at ASC"),
            text("bid_id ASC"),
        ),
        Index("ix_auction_bids_bidder_created", "bidder_id", "created_at"),
    )

    bid_id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=False, start=1), primary_key=True
    )
    auction_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("auctions.auction_id", ondelete="CASCADE"), nullable=False
    )
    bidder_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 0), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    # Relationships
    auction: Mapped["Auction"] = relationship("Auction", back_populates="bids")
    bidder: Mapped["User"] = relationship("User", lazy="selectin")
