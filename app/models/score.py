"""ScoreSnapshot — daily-rolled-up reputation metrics per store.

Task A6 (ONDC Score, BPP-local v1): each store computes a daily Score
snapshot from local Order + RefundRequest data. The headline ``band``
(EXCELLENT / GOOD / FAIR / POOR) is derived deterministically from the
per-attribute values via
``beckn_protocol.score.compute_score_band``.

v1 is BPP-local only — there is no inter-NP /score envelope yet. The
snapshot is persisted so operators (and a future v2 /search ranker) can
read store reputation without re-computing.

Idempotent on ``(store_id, period_start)`` UNIQUE constraint: re-running
the compute for the same period overwrites the row instead of stacking
duplicates.

State machine: none. Each row is a snapshot at compute time.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ScoreSnapshot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "score_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "store_id", "period_start",
            name="uq_score_snapshots_store_period",
        ),
        Index(
            "ix_score_snapshots_store_band",
            "store_id", "band",
        ),
    )

    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stores.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # Per-attribute signals (Numeric so we don't lose precision on the
    # ratios). Stored as 0..1 ratios for completion / return; mean hours
    # for response / resolution; 0..5 average for rating_avg.
    completion_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), nullable=False, default=Decimal("0.0")
    )
    return_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), nullable=False, default=Decimal("0.0")
    )
    avg_response_hours: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 2), nullable=True
    )
    resolution_time_hours: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 2), nullable=True
    )
    rating_avg: Mapped[Decimal] = mapped_column(
        Numeric(3, 2), nullable=False, default=Decimal("0.0")
    )
    # Headline reputation bucket. v1 values: EXCELLENT / GOOD / FAIR / POOR.
    band: Mapped[str] = mapped_column(
        String(16), nullable=False, default="POOR", index=True
    )
    # Useful denormalized counts so operators can see the underlying
    # sample size without re-running the compute query.
    total_orders: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    completed_orders: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    refunded_orders: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    last_computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    # Relationships
    store = relationship("Store")

    def __repr__(self) -> str:
        return (
            f"<ScoreSnapshot(store={self.store_id}, "
            f"band={self.band}, period={self.period_start:%Y-%m-%d})>"
        )
