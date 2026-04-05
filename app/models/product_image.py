"""ProductImage model for product image gallery."""

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ProductImage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "product_images"

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
    )
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    # Relationships
    product: Mapped["Product"] = relationship(back_populates="images")  # noqa: F821

    def __repr__(self) -> str:
        return f"<ProductImage(id={self.id}, product_id={self.product_id})>"
