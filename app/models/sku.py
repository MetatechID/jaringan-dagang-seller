"""SKU model -- product variants with individual pricing and stock."""

import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SKU(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "skus"

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
    )
    variant_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    variant_value: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    sku_code: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )
    price: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False
    )
    original_price: Mapped[Decimal | None] = mapped_column(
        Numeric(15, 2), nullable=True
    )
    stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    weight_grams: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )

    # Relationships
    product: Mapped["Product"] = relationship(back_populates="skus")  # noqa: F821
    marketplace_maps: Mapped[list["MarketplaceProductMap"]] = relationship(  # noqa: F821
        back_populates="sku", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<SKU(id={self.id}, sku_code='{self.sku_code}', price={self.price})>"
