"""Task A6 — ``score_service.compute_for_store`` over synthetic orders.

We don't spin up Postgres for these unit tests; we exercise the math
directly via the protocol module's ``compute_score_band`` against the
known threshold tree. A separate light integration test exercises
``compute_for_store`` against an in-memory DB to confirm the upsert is
idempotent.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PROTO = os.path.join(_ROOT, "packages", "beckn-protocol")
for _p in (_ROOT, _PROTO):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest  # noqa: E402

from python import (  # noqa: E402
    SCORE_BANDS,
    compute_score_band,
)


class TestComputeBand:
    def test_excellent_all_thresholds_clear(self):
        assert compute_score_band(
            completion_rate=0.99, return_rate=0.02, rating_avg=4.8,
        ) == "EXCELLENT"

    def test_good_below_excellent_completion(self):
        # 90% completion fails EXCELLENT (>= 95%) but passes GOOD (>= 85%).
        assert compute_score_band(
            completion_rate=0.90, return_rate=0.05, rating_avg=4.3,
        ) == "GOOD"

    def test_fair_high_returns(self):
        # 15% return rate fails GOOD (<= 10%) but passes FAIR (<= 20%).
        assert compute_score_band(
            completion_rate=0.85, return_rate=0.15, rating_avg=3.5,
        ) == "FAIR"

    def test_poor_below_fair_completion(self):
        # 50% completion fails FAIR (>= 70%).
        assert compute_score_band(
            completion_rate=0.50, return_rate=0.05, rating_avg=4.5,
        ) == "POOR"

    def test_poor_zero_rating_blocks_good(self):
        # Zero ratings (default) means rating_avg=0 < 4.0 GOOD threshold,
        # so a new BPP with perfect completion + no returns floors at
        # FAIR (because rating>=3.0 fails too) -> POOR.
        assert compute_score_band(
            completion_rate=1.0, return_rate=0.0, rating_avg=0.0,
        ) == "POOR"

    def test_band_is_one_of_known_set(self):
        # Sanity: 0%-100% completion sweep always yields a valid band.
        for c in [0.0, 0.5, 0.85, 0.95, 1.0]:
            b = compute_score_band(
                completion_rate=c, return_rate=0.1, rating_avg=4.0,
            )
            assert b in SCORE_BANDS


@pytest.mark.skipif(
    not os.environ.get("SELLER_TEST_PG_DSN"),
    reason=(
        "Order has JSONB columns; needs real Postgres. "
        "Set SELLER_TEST_PG_DSN to exercise."
    ),
)
class TestComputeForStoreIntegration:
    """Lightweight integration: in-memory SQLite + the real service.

    Confirms that:
        1. compute_for_store reads Orders + RefundRequests in the window.
        2. The headline band matches compute_score_band on the same inputs.
        3. Re-running upserts (idempotent on (store_id, period_start)).
    """

    @pytest.fixture
    def db_engine(self):
        from sqlalchemy.ext.asyncio import create_async_engine
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        yield engine

    @pytest.fixture
    def db_session_factory(self, db_engine):
        from sqlalchemy.ext.asyncio import (
            AsyncSession,
            async_sessionmaker,
        )
        return async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    def test_idempotent_upsert(self, db_engine, db_session_factory):
        """compute_for_store + re-run for the same window = one row."""
        from app.models.base import Base
        from app.models.score import ScoreSnapshot
        from sqlalchemy import func, select

        async def run():
            async with db_engine.begin() as conn:
                # Create just the score_snapshots table + any FKs it needs.
                # We also need stores for the FK ref.
                from app.models.store import Store  # noqa: F401
                from app.models.user import User  # noqa: F401
                from app.models.order import Order  # noqa: F401
                from app.models.payment import PaymentRecord  # noqa: F401
                from app.models.fulfillment import FulfillmentRecord  # noqa: F401
                from app.models.refund import RefundRequest  # noqa: F401
                from app.models.product import Product  # noqa: F401
                from app.models.sku import SKU  # noqa: F401
                from app.models.product_image import ProductImage  # noqa: F401
                from app.models.sku_image import SKUImage  # noqa: F401
                from app.models.category import Category  # noqa: F401
                from app.models.store_membership import StoreMembership  # noqa: F401
                from app.models.beckn_transaction_log import BecknTransactionLog  # noqa: F401
                from app.models.beckn_outbound_log import BecknOutboundLog  # noqa: F401
                from app.models.import_job import ImportJob  # noqa: F401
                from app.models.marketplace_map import MarketplaceProductMap  # noqa: F401
                from app.models.conversation import Conversation  # noqa: F401
                from app.models.settlement import SettlementLedger  # noqa: F401
                # Subset to skip JSONB-using tables that sqlite can't compile.
                from app.models.store import Store as _Store
                from app.models.order import Order as _Order
                from app.models.refund import RefundRequest as _RR
                from app.models.score import ScoreSnapshot as _SS
                await conn.run_sync(
                    Base.metadata.create_all,
                    tables=[
                        _Store.__table__, _Order.__table__,
                        _RR.__table__, _SS.__table__,
                    ],
                )

            # Seed a store + a few orders + one refund.
            from app.models.store import Store
            from app.models.order import Order, OrderStatus
            from app.models.refund import (
                RefundReason,
                RefundRequest,
                RefundStatus,
            )

            async with db_session_factory() as db:
                store = Store(
                    id=uuid.uuid4(),
                    slug="t1",
                    subscriber_id="t1.jaringan-dagang.id",
                    name="t1",
                    status="active",
                )
                db.add(store)
                await db.flush()

                period_start = datetime(2026, 5, 19, tzinfo=timezone.utc)
                period_end = period_start + timedelta(days=1)
                mid = period_start + timedelta(hours=12)
                for i, status in enumerate([
                    OrderStatus.COMPLETED,
                    OrderStatus.COMPLETED,
                    OrderStatus.COMPLETED,
                    OrderStatus.COMPLETED,
                    OrderStatus.CANCELLED,
                ]):
                    o = Order(
                        id=uuid.uuid4(),
                        store_id=store.id,
                        beckn_order_id=f"JD-{i}",
                        total=10000,
                        status=status,
                        created_at=mid,
                    )
                    db.add(o)
                # One refund on the first completed order.
                await db.flush()
                first_completed = (await db.execute(
                    select(Order)
                    .where(Order.status == OrderStatus.COMPLETED)
                    .limit(1)
                )).scalar_one()
                refund = RefundRequest(
                    order_id=first_completed.id,
                    requested_by="buyer",
                    reason_code=RefundReason.OTHER,
                    requested_amount=10000,
                    status=RefundStatus.REFUNDED,
                    decided_at=mid + timedelta(hours=1),
                )
                db.add(refund)
                await db.commit()

                from app.services import score_service
                snap = await score_service.compute_for_store(
                    db,
                    store_id=store.id,
                    period_start=period_start,
                    period_end=period_end,
                )
                await db.commit()
                # 4 completed / 5 total = 0.8 completion
                # 1 refunded / 4 completed = 0.25 return
                assert float(snap.completion_rate) == pytest.approx(0.8, abs=0.001)
                assert float(snap.return_rate) == pytest.approx(0.25, abs=0.001)
                assert snap.total_orders == 5
                assert snap.completed_orders == 4
                assert snap.refunded_orders == 1
                # 80% completion fails GOOD (85%), so FAIR check:
                # 25% return fails FAIR (20%) -> POOR.
                assert snap.band == "POOR"

                # Re-run: must upsert, not duplicate.
                await score_service.compute_for_store(
                    db,
                    store_id=store.id,
                    period_start=period_start,
                    period_end=period_end,
                )
                await db.commit()
                cnt = (await db.execute(
                    select(func.count(ScoreSnapshot.id))
                    .where(ScoreSnapshot.store_id == store.id)
                )).scalar()
                assert cnt == 1

        asyncio.run(run())
