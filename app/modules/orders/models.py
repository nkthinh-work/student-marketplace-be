from datetime import datetime
from decimal import Decimal
import enum
from typing import Optional, TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.modules.auctions.models import Auction


class OrderStatus(str, enum.Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    DELIVERING = "DELIVERING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, enum.Enum):
    UNPAID = "UNPAID"
    VERIFYING = "VERIFYING"
    PAID = "PAID"


class PaymentMethod(str, enum.Enum):
    CASH_ON_MEETUP = "CASH_ON_MEETUP"
    BANK_TRANSFER = "BANK_TRANSFER"
    OTHER = "OTHER"


class FulfillmentMethod(str, enum.Enum):
    MEETUP = "MEETUP"
    SHIPPING = "SHIPPING"


class CancelledBy(str, enum.Enum):
    BUYER = "BUYER"
    SELLER = "SELLER"
    SYSTEM = "SYSTEM"


payment_status_enum = PgEnum(
    PaymentStatus,
    name="payment_status_t",
    create_type=False,
)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("buyer_id <> seller_id", name="chk_orders_buyer_not_seller"),
        CheckConstraint(
            "status IN ('PENDING', 'CONFIRMED', 'DELIVERING', 'COMPLETED', 'CANCELLED')",
            name="chk_orders_status",
        ),
        CheckConstraint(
            "payment_method IN ('CASH_ON_MEETUP', 'BANK_TRANSFER', 'OTHER')",
            name="chk_orders_payment_method",
        ),
        CheckConstraint(
            "fulfillment_method IN ('MEETUP', 'SHIPPING')",
            name="chk_orders_fulfillment_method",
        ),
        CheckConstraint(
            "cancelled_by IS NULL OR cancelled_by IN ('BUYER', 'SELLER', 'SYSTEM')",
            name="chk_orders_cancelled_by",
        ),
        CheckConstraint(
            "payment_status <> 'VERIFYING' OR payment_receipt_url IS NOT NULL",
            name="chk_orders_verifying_receipt",
        ),
        CheckConstraint(
            "payment_status <> 'PAID' OR paid_confirmed_at IS NOT NULL",
            name="chk_orders_paid_confirmed",
        ),
        UniqueConstraint("order_code", name="ux_orders_order_code"),
        Index(
            "ux_orders_auction_id",
            "auction_id",
            unique=True,
            postgresql_where=text("auction_id IS NOT NULL"),
        ),
        Index("ix_orders_buyer_status_created", "buyer_id", "status", "created_at"),
        Index("ix_orders_seller_status_created", "seller_id", "status", "created_at"),
        Index("ix_orders_status_paystatus_autocancel", "status", "payment_status", "auto_cancel_at"),
        Index("ix_orders_paystatus_receipt_uploaded", "payment_status", "receipt_uploaded_at"),
    )

    order_id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=False, start=1), primary_key=True
    )
    order_code: Mapped[str] = mapped_column(
        String(20), unique=True, nullable=False
    )
    buyer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False
    )
    seller_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.user_id", ondelete="RESTRICT"), nullable=False
    )
    auction_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("auctions.auction_id", ondelete="RESTRICT"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(12),
        nullable=False,
        default=OrderStatus.PENDING.value,
        server_default=OrderStatus.PENDING.value,
    )
    payment_method: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=PaymentMethod.CASH_ON_MEETUP.value,
        server_default=PaymentMethod.CASH_ON_MEETUP.value,
    )
    payment_status: Mapped[PaymentStatus] = mapped_column(
        payment_status_enum,
        nullable=False,
        default=PaymentStatus.UNPAID,
        server_default=PaymentStatus.UNPAID.value,
    )
    payment_receipt_url: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True
    )
    receipt_uploaded_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    paid_confirmed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    payment_note: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    payment_bank_bin: Mapped[Optional[str]] = mapped_column(
        String(10), nullable=True
    )
    payment_bank_account_number: Mapped[Optional[str]] = mapped_column(
        String(30), nullable=True
    )
    payment_bank_account_name: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )
    fulfillment_method: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default=FulfillmentMethod.MEETUP.value,
        server_default=FulfillmentMethod.MEETUP.value,
    )
    meetup_place: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    meetup_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    shipping_address: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True
    )
    shipping_expected_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    contact_name: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    contact_phone: Mapped[str] = mapped_column(
        String(20), nullable=False
    )
    buyer_note: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True
    )
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 0), nullable=False
    )
    auto_cancel_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    cancelled_by: Mapped[Optional[str]] = mapped_column(
        String(10), nullable=True
    )
    cancel_reason: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    buyer = relationship("User", foreign_keys=[buyer_id])
    seller = relationship("User", foreign_keys=[seller_id])
    auction = relationship("Auction", foreign_keys=[auction_id])
    items = relationship(
        "OrderItem", back_populates="order", cascade="all, delete-orphan"
    )
    status_history = relationship(
        "OrderStatusHistory",
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="OrderStatusHistory.created_at.asc()",
    )


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="chk_order_items_quantity"),
        CheckConstraint("price_at_purchase >= 0", name="chk_order_items_price"),
        UniqueConstraint("order_id", "product_id", name="ux_order_items_order_product"),
        Index("ix_order_items_product_id", "product_id"),
    )

    order_item_id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=False, start=1), primary_key=True
    )
    order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("orders.order_id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("products.product_id", ondelete="RESTRICT"), nullable=False
    )
    product_title: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    product_image_url: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True
    )
    quantity: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    price_at_purchase: Mapped[Decimal] = mapped_column(
        Numeric(12, 0), nullable=False
    )

    order = relationship("Order", back_populates="items")
    product = relationship("Product")


class OrderStatusHistory(Base):
    __tablename__ = "order_status_history"
    __table_args__ = (
        Index("ix_order_status_history_order_id_created", "order_id", "created_at"),
    )

    history_id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=False, start=1), primary_key=True
    )
    order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("orders.order_id", ondelete="CASCADE"), nullable=False
    )
    from_status: Mapped[Optional[str]] = mapped_column(
        String(12), nullable=True
    )
    to_status: Mapped[str] = mapped_column(
        String(12), nullable=False
    )
    changed_by: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    order = relationship("Order", back_populates="status_history")
    user = relationship("User", foreign_keys=[changed_by])
