"""Order model for Beckn orders received from BAPs."""

import enum
import uuid
from decimal import Decimal

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class OrderStatus(str, enum.Enum):
    CREATED = "created"
    ACCEPTED = "accepted"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


# Valid order state transitions
ORDER_STATE_TRANSITIONS: dict[OrderStatus, list[OrderStatus]] = {
    OrderStatus.CREATED: [OrderStatus.ACCEPTED, OrderStatus.CANCELLED],
    OrderStatus.ACCEPTED: [OrderStatus.IN_PROGRESS, OrderStatus.CANCELLED],
    OrderStatus.IN_PROGRESS: [OrderStatus.COMPLETED, OrderStatus.CANCELLED],
    OrderStatus.COMPLETED: [],
    OrderStatus.CANCELLED: [],
}


class Order(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "orders"

    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stores.id", ondelete="CASCADE"),
        nullable=False,
    )
    beckn_order_id: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True, index=True
    )
    buyer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    buyer_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    buyer_email: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    billing_address: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True
    )
    shipping_address: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True
    )
    status: Mapped[OrderStatus] = mapped_column(
        SAEnum(OrderStatus, name="order_status", create_constraint=True),
        nullable=False,
        default=OrderStatus.CREATED,
    )
    total: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=0
    )
    currency: Mapped[str] = mapped_column(
        String(10), nullable=False, default="IDR"
    )
    items: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    payment_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    fulfillment_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )

    # Relationships
    store: Mapped["Store"] = relationship(back_populates="orders")  # noqa: F821
    payment: Mapped["PaymentRecord | None"] = relationship(  # noqa: F821
        back_populates="order", uselist=False, cascade="all, delete-orphan"
    )
    fulfillment: Mapped["FulfillmentRecord | None"] = relationship(  # noqa: F821
        back_populates="order", uselist=False, cascade="all, delete-orphan"
    )

    def can_transition_to(self, new_status: OrderStatus) -> bool:
        """Check whether a transition from the current status to new_status is valid."""
        return new_status in ORDER_STATE_TRANSITIONS.get(self.status, [])

    def __repr__(self) -> str:
        return f"<Order(id={self.id}, status='{self.status}')>"
