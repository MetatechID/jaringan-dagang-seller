"""RefundRequest — tracks buyer-initiated refund disputes through to Xendit settlement.

State machine:
    PENDING → APPROVED → REFUNDED   (success path; APPROVED waits for Xendit webhook)
    PENDING → DENIED                (seller rejects)
    APPROVED → FAILED               (Xendit refund call errored; seller can retry)

At most one open request (PENDING or APPROVED) per order.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime, Enum as SAEnum, ForeignKey, Index, Integer, String, Text, func, text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class RefundStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    REFUNDED = "refunded"
    FAILED = "failed"


class RefundReason(str, enum.Enum):
    ITEM_NOT_RECEIVED = "item_not_received"
    ITEM_DAMAGED = "item_damaged"
    WRONG_ITEM = "wrong_item"
    CHANGED_MIND = "changed_mind"
    OTHER = "other"


class RefundRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "refund_requests"

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    requested_by: Mapped[str] = mapped_column(
        String(20), nullable=False, default="buyer"
    )
    reason_code: Mapped[RefundReason] = mapped_column(
        SAEnum(RefundReason, name="refund_reason", create_constraint=True),
        nullable=False,
        default=RefundReason.OTHER,
    )
    reason_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[RefundStatus] = mapped_column(
        SAEnum(RefundStatus, name="refund_status", create_constraint=True),
        nullable=False,
        default=RefundStatus.PENDING,
        index=True,
    )
    seller_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decided_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    xendit_refund_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    order = relationship("Order")

    def __repr__(self) -> str:
        return f"<RefundRequest(id={self.id}, order={self.order_id}, status={self.status})>"


# At most one open request per order (PENDING or APPROVED).
Index(
    "uq_refund_request_open_per_order",
    RefundRequest.order_id,
    unique=True,
    postgresql_where=text("status IN ('pending', 'approved')"),
)
