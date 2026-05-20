"""Task A6 — ``settlement_service`` pure-function math + record_for_order upsert.

Math is exercised via ``_compute_payable_amount`` (the deterministic
core); the upsert behaviour is exercised against an in-memory SQLite
DB with synthetic orders + payments + refunds.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PROTO = os.path.join(_ROOT, "packages", "beckn-protocol")
for _p in (_ROOT, _PROTO):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest  # noqa: E402

from app.services import settlement_service  # noqa: E402


class TestComputePayable:
    """Direct math tests on ``_compute_payable_amount``."""

    def test_paid_minus_fee_minus_refund(self):
        # 100000 paid, 3% fee = 3000 -> net 97000.
        # 20000 refunded -> 77000.
        assert settlement_service._compute_payable_amount(
            paid_amount=100000, refunded_amount=20000,
        ) == 77000

    def test_zero_refund(self):
        assert settlement_service._compute_payable_amount(
            paid_amount=50000, refunded_amount=0,
        ) == 50000 - int(50000 * 0.03)

    def test_full_refund_clamps_at_zero(self):
        # Refund exceeds net -> v1 clamps at 0 (the negative balance is
        # captured in v2 as a counterparty owed FROM BPP back to BAP).
        assert settlement_service._compute_payable_amount(
            paid_amount=10000, refunded_amount=20000,
        ) == 0

    def test_custom_fee_pct(self):
        # 5% fee on 100000 = 5000 -> net 95000.
        assert settlement_service._compute_payable_amount(
            paid_amount=100000, refunded_amount=0,
            buyer_app_finder_fee_pct=Decimal("0.05"),
        ) == 95000

    def test_negative_inputs_floored(self):
        # Defensive: negative inputs are treated as zero.
        assert settlement_service._compute_payable_amount(
            paid_amount=-5000, refunded_amount=-1000,
        ) == 0


@pytest.mark.skipif(
    not os.environ.get("SELLER_TEST_PG_DSN"),
    reason=(
        "Order/PaymentRecord use JSONB; needs real Postgres. "
        "Set SELLER_TEST_PG_DSN to exercise."
    ),
)
class TestRecordForOrder:
    """Lightweight integration: in-memory SQLite + record_for_order upsert."""

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

    def test_record_then_re_record_is_idempotent(
        self, db_engine, db_session_factory
    ):
        """record_for_order is one-row-per-order and re-emits don't dup."""
        from app.models.base import Base
        from app.models.settlement import SettlementLedger
        from sqlalchemy import func, select

        async def run():
            async with db_engine.begin() as conn:
                # Import every model so create_all picks them up.
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
                from app.models.score import ScoreSnapshot  # noqa: F401
                # Restrict create_all to the subset we actually need —
                # beckn_transaction_logs/outbound_logs use JSONB which
                # sqlite can't compile.
                await conn.run_sync(
                    Base.metadata.create_all,
                    tables=[
                        Store.__table__,
                        Order.__table__,
                        PaymentRecord.__table__,
                        RefundRequest.__table__,
                        SettlementLedger.__table__,
                    ],
                )

            from app.models.order import Order, OrderStatus
            from app.models.payment import PaymentRecord, PaymentStatus
            from app.models.refund import (
                RefundReason,
                RefundRequest,
                RefundStatus,
            )
            from app.models.store import Store

            async with db_session_factory() as db:
                store = Store(
                    id=uuid.uuid4(),
                    slug="t2",
                    subscriber_id="t2.jaringan-dagang.id",
                    name="t2",
                    status="active",
                )
                db.add(store)
                await db.flush()
                order = Order(
                    id=uuid.uuid4(),
                    store_id=store.id,
                    beckn_order_id="JD-S1",
                    total=100000,
                    status=OrderStatus.COMPLETED,
                )
                db.add(order)
                await db.flush()
                pay = PaymentRecord(
                    id=uuid.uuid4(),
                    order_id=order.id,
                    amount=100000,
                    status=PaymentStatus.PAID,
                )
                db.add(pay)
                refund = RefundRequest(
                    order_id=order.id,
                    requested_by="buyer",
                    reason_code=RefundReason.OTHER,
                    requested_amount=20000,
                    status=RefundStatus.REFUNDED,
                    decided_at=datetime.now(timezone.utc),
                )
                db.add(refund)
                await db.commit()

                rec = await settlement_service.record_for_order(
                    db, order_id=order.id,
                    settlement_basis="DELIVERY", settlement_window="P1D",
                )
                await db.commit()
                # 100000 paid - 3000 fee - 20000 refund = 77000 payable.
                assert int(rec["counterparties"][0]["amount"]) == 77000
                assert rec["settlement_basis"] == "DELIVERY"
                assert rec["settlement_window"]["duration"] == "P1D"
                assert rec["settlement_status"] == "NOT_PAID"

                # Re-emit: same row (idempotent on order_id UNIQUE).
                rec2 = await settlement_service.record_for_order(
                    db, order_id=order.id,
                    settlement_basis="DELIVERY", settlement_window="P1D",
                )
                await db.commit()
                assert rec2["id"] == rec["id"]
                cnt = (await db.execute(
                    select(func.count(SettlementLedger.id))
                    .where(SettlementLedger.order_id == order.id)
                )).scalar()
                assert cnt == 1

        asyncio.run(run())

    def test_unknown_order_raises(self, db_engine, db_session_factory):
        from app.models.base import Base
        from app.services.settlement_service import SettlementError

        async def run():
            async with db_engine.begin() as conn:
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
                from app.models.score import ScoreSnapshot  # noqa: F401
                # Subset to skip JSONB tables sqlite can't compile.
                await conn.run_sync(
                    Base.metadata.create_all,
                    tables=[
                        Store.__table__,
                        Order.__table__,
                        PaymentRecord.__table__,
                        RefundRequest.__table__,
                        SettlementLedger.__table__,
                    ],
                )

            async with db_session_factory() as db:
                with pytest.raises(SettlementError):
                    await settlement_service.record_for_order(
                        db, order_id=uuid.uuid4(),
                    )

        asyncio.run(run())
