from datetime import datetime
import enum
from typing import Optional, Any
import uuid
from sqlalchemy import (
    BigInteger,
    Boolean,
    JSON,
    String,
    DateTime,
    CheckConstraint,
    UniqueConstraint,
    ForeignKey,
    Enum as SQLEnum,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


class UserRole(str, enum.Enum):
    STUDENT = "STUDENT"
    ADMIN = "ADMIN"


class UserStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    BANNED = "BANNED"
    INACTIVE = "INACTIVE"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('STUDENT', 'ADMIN')", name="chk_users_role"),
        UniqueConstraint("email", name="ux_users_email"),
        UniqueConstraint("public_id", name="ux_users_public_id"),
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )
    full_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    phone: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
    )
    show_phone_publicly: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    social_links: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(
        JSON,
        nullable=True,
    )
    avatar_url: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )
    bio: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )
    delivery_area: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    default_meetup_area: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
    )
    bank_bin: Mapped[Optional[str]] = mapped_column(
        String(10),
        nullable=True,
    )
    bank_account_number: Mapped[Optional[str]] = mapped_column(
        String(30),
        nullable=True,
    )
    bank_account_name: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    role: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default=UserRole.STUDENT.value,
        server_default="STUDENT",
    )
    status: Mapped[UserStatus] = mapped_column(
        SQLEnum(UserStatus, name="user_status", native_enum=True),
        nullable=False,
        default=UserStatus.ACTIVE,
        server_default="ACTIVE",
    )
    last_active_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # 1:1 relationship with UserAuthIdentity
    auth_identity: Mapped[Optional["UserAuthIdentity"]] = relationship(
        "UserAuthIdentity",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )


class UserAuthIdentity(Base):
    __tablename__ = "user_auth_identities"
    __table_args__ = (
        CheckConstraint("provider IN ('FIREBASE')", name="chk_user_auth_identities_provider"),
        UniqueConstraint("provider", "provider_uid", name="ux_user_auth_identities_provider_uid"),
        UniqueConstraint("user_id", name="ux_user_auth_identities_user_id"),
    )

    user_auth_identity_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    provider: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="FIREBASE",
        server_default="FIREBASE",
    )
    provider_uid: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    user: Mapped["User"] = relationship(
        "User",
        back_populates="auth_identity",
    )
