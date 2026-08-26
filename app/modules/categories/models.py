from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import (
    Integer,
    String,
    Boolean,
    DateTime,
    Index,
    text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

if TYPE_CHECKING:
    from app.modules.products.models import Product


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (
        Index(
            "ux_categories_slug",
            "slug",
            unique=True,
            postgresql_where=text("is_deleted = FALSE"),
        ),
    )

    category_id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    slug: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("FALSE"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
    )

    # Relationships
    products: Mapped[list["Product"]] = relationship(
        "Product",
        back_populates="category",
        lazy="selectin",
    )
