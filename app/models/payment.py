"""Payment model for tracking Xendit payment lifecycle."""

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    PAID = "paid"
    EXPIRED = "expired"
    FAILED = "failed"
    REFUNDED = "refunded"


class PaymentRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "payments"

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    xendit_invoice_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    xendit_payment_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False
    )
    method: Mapped[str | None] = mapped_column(String(100), nullable=True)
    channel: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[PaymentStatus] = mapped_column(
        SAEnum(PaymentStatus, name="payment_status", create_constraint=True),
        nullable=False,
        default=PaymentStatus.PENDING,
    )
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    callback_data: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True
    )

    # Relationships
    order: Mapped["Order"] = relationship(back_populates="payment")  # noqa: F821

    def __repr__(self) -> str:
        return f"<PaymentRecord(id={self.id}, status='{self.status}')>"
