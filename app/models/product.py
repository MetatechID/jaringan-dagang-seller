"""Product model with JSONB attributes for category-specific fields."""

import enum
import uuid

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ProductStatus(str, enum.Enum):
    ACTIVE = "active"
    DRAFT = "draft"
    ARCHIVED = "archived"


class Product(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "products"

    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stores.id", ondelete="CASCADE"),
        nullable=False,
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("categories.id", ondelete="SET NULL"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sku: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True
    )
    status: Mapped[ProductStatus] = mapped_column(
        SAEnum(ProductStatus, name="product_status", create_constraint=True),
        nullable=False,
        default=ProductStatus.DRAFT,
    )
    attributes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Relationships
    store: Mapped["Store"] = relationship(back_populates="products")  # noqa: F821
    category: Mapped["Category | None"] = relationship(  # noqa: F821
        back_populates="products"
    )
    images: Mapped[list["ProductImage"]] = relationship(  # noqa: F821
        back_populates="product", cascade="all, delete-orphan",
        order_by="ProductImage.position",
    )
    skus: Mapped[list["SKU"]] = relationship(  # noqa: F821
        back_populates="product", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Product(id={self.id}, name='{self.name}')>"
