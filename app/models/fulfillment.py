"""Fulfillment model for tracking shipping/delivery lifecycle."""

import enum
import uuid
from decimal import Decimal

from sqlalchemy import Enum as SAEnum, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class FulfillmentStatus(str, enum.Enum):
    PENDING = "pending"
    PICKED_UP = "picked_up"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"


class FulfillmentRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "fulfillments"

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="Delivery"
    )
    courier_code: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )
    courier_service: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    awb_number: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True
    )
    status: Mapped[FulfillmentStatus] = mapped_column(
        SAEnum(
            FulfillmentStatus,
            name="fulfillment_status",
            create_constraint=True,
        ),
        nullable=False,
        default=FulfillmentStatus.PENDING,
    )
    tracking_url: Mapped[str | None] = mapped_column(
        String(1024), nullable=True
    )
    shipping_cost: Mapped[Decimal | None] = mapped_column(
        Numeric(15, 2), nullable=True
    )

    # Relationships
    order: Mapped["Order"] = relationship(back_populates="fulfillment")  # noqa: F821

    def __repr__(self) -> str:
        return f"<FulfillmentRecord(id={self.id}, status='{self.status}')>"
