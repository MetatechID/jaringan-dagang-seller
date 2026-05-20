"""SettlementLedger — per-order RSP settlement record.

Task A6 (ONDC RSP, narrow): each fulfilled order gets ONE
SettlementLedger row that records the payable amount the BPP is owed
post-fees-and-refunds, the basis (DELIVERY / PICKUP / RECEIPT), the
window (P1D / P3D / P7D), and the current status (NOT_PAID / PAID /
PARTIAL_PAID).

v1 doesn't move money — the operator settles out-of-band via existing
bank-rail tooling and flips ``settlement_status`` manually (or via a
follow-up worker). The ledger row is the wire-correlated record the
BAP receives on /on_settle.

State machine (managed in services/settlement_service.py):
    NOT_PAID       -> PAID         (operator confirms settlement)
    NOT_PAID       -> PARTIAL_PAID (operator records partial)
    PARTIAL_PAID   -> PAID         (operator records the remainder)

Idempotent on ``order_id`` (one ledger row per order; UNIQUE constraint).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    String,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SettlementStatus(str, enum.Enum):
    """RSP v1 settlement statuses (mirrors network-extension/enums/rsp.yaml)."""

    NOT_PAID = "NOT_PAID"
    PAID = "PAID"
    PARTIAL_PAID = "PARTIAL_PAID"


class SettlementBasis(str, enum.Enum):
    """RSP v1 settlement basis codes."""

    DELIVERY = "DELIVERY"
    PICKUP = "PICKUP"
    RECEIPT = "RECEIPT"


class SettlementWindow(str, enum.Enum):
    """RSP v1 ISO 8601 settlement window codes."""

    P1D = "P1D"
    P3D = "P3D"
    P7D = "P7D"


class SettlementLedger(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "settlement_ledger"

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,        # one ledger row per order
        index=True,
    )
    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("payments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Amount in IDR whole rupiahs (BigInteger to match Order.escrow_amount_idr).
    payable_amount: Mapped[int] = mapped_column(
        BigInteger, nullable=False
    )
    settlement_basis: Mapped[SettlementBasis] = mapped_column(
        SAEnum(
            SettlementBasis,
            name="settlement_basis",
            create_constraint=True,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=SettlementBasis.DELIVERY,
    )
    settlement_window: Mapped[SettlementWindow] = mapped_column(
        SAEnum(
            SettlementWindow,
            name="settlement_window",
            create_constraint=True,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=SettlementWindow.P1D,
    )
    settlement_status: Mapped[SettlementStatus] = mapped_column(
        SAEnum(
            SettlementStatus,
            name="settlement_status",
            create_constraint=True,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=SettlementStatus.NOT_PAID,
        index=True,
    )
    # Operator-supplied reference (e.g. bank transfer reference). Surfaced
    # to the BAP in /on_settle so both sides can correlate to off-network
    # bank statements.
    settlement_reference: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    settled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    order = relationship("Order")

    def __repr__(self) -> str:
        return (
            f"<SettlementLedger(order={self.order_id}, "
            f"amount={self.payable_amount}, status={self.settlement_status})>"
        )
