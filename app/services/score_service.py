"""ONDC Score (reputation) service (Task A6).

Narrow v1 scope: compute a daily ScoreSnapshot per store from local
Order + RefundRequest data. v1 is BPP-local — there is no inter-NP
/score envelope yet; the snapshot is persisted so operators can read
store reputation and a future v2 /search ranker can consume it.

Headline ``band`` (EXCELLENT / GOOD / FAIR / POOR) is derived
deterministically from the per-attribute values via
``beckn_protocol.score.compute_score_band``.

Pure function: no external network calls. Callers commit.
"""

from __future__ import annotations

import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order, OrderStatus
from app.models.refund import RefundRequest, RefundStatus
from app.models.score import ScoreSnapshot

# Make beckn-protocol importable
_proto_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "packages", "beckn-protocol")
)
if _proto_path not in sys.path:
    sys.path.insert(0, _proto_path)

from python import compute_score_band  # noqa: E402

logger = logging.getLogger(__name__)


class ScoreError(Exception):
    """Application-level score-compute errors."""


def _safe_ratio(numerator: int, denominator: int) -> Decimal:
    """Return numerator/denominator as a Decimal in [0, 1], 0 if denom is 0."""
    if denominator <= 0:
        return Decimal("0.0")
    r = Decimal(numerator) / Decimal(denominator)
    if r < 0:
        return Decimal("0.0")
    if r > 1:
        return Decimal("1.0")
    return r


async def compute_for_store(
    db: AsyncSession,
    *,
    store_id: uuid.UUID,
    period_start: datetime,
    period_end: datetime,
) -> ScoreSnapshot:
    """Compute + upsert a daily ScoreSnapshot for ``store_id`` over the period.

    Args:
        db: async session; caller commits.
        store_id: store whose reputation to compute.
        period_start / period_end: half-open window (start inclusive, end
            exclusive). v1 callers pass a 24-hour daily window aligned to
            UTC midnight.

    Returns:
        The persisted ScoreSnapshot row. Idempotent on
        ``(store_id, period_start)`` — re-running overwrites the row.

    Metric math:
        completion_rate = completed / total
            (where completed = orders that reached OrderStatus.COMPLETED
             without cancellation in the window).
        return_rate     = refunded / completed
            (refunded = RefundRequest.status==REFUNDED in the window).
        rating_avg      = 0.0   (v1: no Rating ingest yet)
        response_hours  = None  (v1: no /issue ack timestamp yet)
        resolution_hours= None  (v1: no /issue resolution timestamp yet)

    The headline band is derived from
    ``compute_score_band(completion_rate, return_rate, rating_avg)``.
    """
    if period_end <= period_start:
        raise ScoreError(
            f"period_end {period_end} must be after period_start {period_start}"
        )

    # Count Orders in the period for this store.
    orders = (await db.execute(
        select(Order)
        .where(Order.store_id == store_id)
        .where(Order.created_at >= period_start)
        .where(Order.created_at < period_end)
    )).scalars().all()
    total_orders = len(orders)
    completed_orders = sum(
        1 for o in orders if o.status == OrderStatus.COMPLETED
    )

    # Count REFUNDED RefundRequests in the period (decided_at in the window).
    refunds = (await db.execute(
        select(RefundRequest)
        .join(Order, Order.id == RefundRequest.order_id)
        .where(Order.store_id == store_id)
        .where(RefundRequest.status == RefundStatus.REFUNDED)
        .where(RefundRequest.decided_at >= period_start)
        .where(RefundRequest.decided_at < period_end)
    )).scalars().all()
    refunded_orders = len(refunds)

    completion_rate = _safe_ratio(completed_orders, total_orders)
    # Return rate denominator is "completed" — a refund on a non-completed
    # order doesn't drag down the return rate (it shows up via the
    # completion_rate dip instead).
    return_rate = _safe_ratio(refunded_orders, max(completed_orders, 1))
    rating_avg = Decimal("0.0")  # v1: no Rating ingest yet

    band = compute_score_band(
        completion_rate=float(completion_rate),
        return_rate=float(return_rate),
        rating_avg=float(rating_avg),
    )

    now = datetime.now(timezone.utc)

    # Idempotent upsert on (store_id, period_start).
    existing = (await db.execute(
        select(ScoreSnapshot)
        .where(ScoreSnapshot.store_id == store_id)
        .where(ScoreSnapshot.period_start == period_start)
    )).scalar_one_or_none()

    if existing is None:
        snap = ScoreSnapshot(
            store_id=store_id,
            period_start=period_start,
            period_end=period_end,
            completion_rate=completion_rate,
            return_rate=return_rate,
            avg_response_hours=None,
            resolution_time_hours=None,
            rating_avg=rating_avg,
            band=band,
            total_orders=total_orders,
            completed_orders=completed_orders,
            refunded_orders=refunded_orders,
            last_computed_at=now,
        )
        db.add(snap)
        await db.flush()
        return snap
    else:
        existing.period_end = period_end
        existing.completion_rate = completion_rate
        existing.return_rate = return_rate
        existing.rating_avg = rating_avg
        existing.band = band
        existing.total_orders = total_orders
        existing.completed_orders = completed_orders
        existing.refunded_orders = refunded_orders
        existing.last_computed_at = now
        await db.flush()
        return existing
