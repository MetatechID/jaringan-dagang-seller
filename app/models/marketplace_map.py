"""MarketplaceProductMap model for TikTok Shop / marketplace sync mapping."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class MarketplaceProductMap(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "marketplace_product_maps"

    sku_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("skus.id", ondelete="CASCADE"),
        nullable=False,
    )
    marketplace_name: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    marketplace_item_id: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    sku: Mapped["SKU"] = relationship(back_populates="marketplace_maps")  # noqa: F821

    def __repr__(self) -> str:
        return (
            f"<MarketplaceProductMap(id={self.id}, "
            f"marketplace='{self.marketplace_name}')>"
        )
