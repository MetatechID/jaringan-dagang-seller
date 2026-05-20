"""Task A6 — ``RefundRequest.bap_issue_id`` dedicated column round-trip.

After A6, `_extract_bap_issue_id` prefers the dedicated column over the
A5-era ``seller_note=bap_issue_id=<uuid>`` overload.
``create_from_beckn_issue`` writes to BOTH (new column + seller_note).
"""

from __future__ import annotations

import asyncio
import os
import sys
import types
import uuid

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PROTO = os.path.join(_ROOT, "packages", "beckn-protocol")
for _p in (_ROOT, _PROTO):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest  # noqa: E402

from app.models.refund import RefundReason, RefundStatus  # noqa: E402
from app.services import refund_service  # noqa: E402


def _row(**overrides):
    base = dict(
        id=uuid.uuid4(),
        order_id=uuid.uuid4(),
        requested_by="buyer",
        reason_code=RefundReason.OTHER,
        reason_text="x",
        requested_amount=10000,
        status=RefundStatus.PENDING,
        seller_note=None,
        error=None,
        bap_issue_id=None,
        decided_at=None,
        decided_by=None,
        xendit_refund_id=None,
    )
    base.update(overrides)
    return types.SimpleNamespace(**base)


class TestExtractBapIssueId:
    def test_prefers_dedicated_column(self):
        # New rows have the column populated; the seller_note stash is
        # ignored even if it carries a different value.
        r = _row(
            bap_issue_id="new-col-uuid",
            seller_note="bap_issue_id=stash-uuid",
        )
        assert refund_service._extract_bap_issue_id(r) == "new-col-uuid"

    def test_falls_back_to_seller_note(self):
        # Pre-A6 rows have only the seller_note stash.
        r = _row(
            bap_issue_id=None,
            seller_note="bap_issue_id=legacy-uuid",
        )
        assert refund_service._extract_bap_issue_id(r) == "legacy-uuid"

    def test_falls_back_to_error_stash(self):
        # Oldest format — error column carried the stash.
        r = _row(
            bap_issue_id=None,
            seller_note=None,
            error="bap_issue_id=oldest-uuid",
        )
        assert refund_service._extract_bap_issue_id(r) == "oldest-uuid"

    def test_returns_none_when_no_stash(self):
        r = _row()
        assert refund_service._extract_bap_issue_id(r) is None

    def test_seller_note_with_free_text_returns_none(self):
        # If seller_note has been overwritten with reason text, it
        # doesn't start with bap_issue_id= and we correctly return None.
        r = _row(seller_note="Refund issued via Xendit.")
        assert refund_service._extract_bap_issue_id(r) is None


@pytest.mark.skipif(
    not os.environ.get("SELLER_TEST_PG_DSN"),
    reason=(
        "Order/PaymentRecord/etc use Postgres JSONB columns that sqlite "
        "cannot compile, so this integration test needs a real Postgres. "
        "Set SELLER_TEST_PG_DSN=postgresql+psycopg://... to exercise."
    ),
)
class TestCreateFromBecknIssueWritesBothFields:
    """Confirms create_from_beckn_issue back-fills column + seller_note."""

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

    def test_writes_column_and_seller_note(
        self, db_engine, db_session_factory
    ):
        from app.models.base import Base
        from app.models.refund import RefundRequest
        from sqlalchemy import select

        async def run():
            async with db_engine.begin() as conn:
                from app.models.store import Store  # noqa: F401
                from app.models.user import User  # noqa: F401
                from app.models.order import Order  # noqa: F401
                from app.models.payment import PaymentRecord  # noqa: F401
                from app.models.fulfillment import FulfillmentRecord  # noqa: F401
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
                # Subset of tables we need — exclude beckn_transaction_logs/
                # beckn_outbound_logs which use Postgres JSONB and don't
                # compile on sqlite. RefundRequest is the unit under test.
                from app.models.refund import RefundRequest as _RR
                await conn.run_sync(
                    Base.metadata.create_all,
                    tables=[Store.__table__, Order.__table__, _RR.__table__],
                )

            from app.models.order import Order, OrderStatus
            from app.models.store import Store

            async with db_session_factory() as db:
                store = Store(
                    id=uuid.uuid4(),
                    slug="t3",
                    subscriber_id="t3.jaringan-dagang.id",
                    name="t3",
                    status="active",
                )
                db.add(store)
                await db.flush()
                order = Order(
                    id=uuid.uuid4(),
                    store_id=store.id,
                    beckn_order_id="JD-S2",
                    total=10000,
                    status=OrderStatus.COMPLETED,
                )
                db.add(order)
                await db.commit()

                req = await refund_service.create_from_beckn_issue(
                    db,
                    order_beckn_id="JD-S2",
                    sub_category="ITM05",
                    reason_text="quality issue",
                    requested_amount=10000,
                    bap_issue_id="issue-from-bap-abc",
                )
                assert req is not None
                # Both fields are populated.
                assert req.bap_issue_id == "issue-from-bap-abc"
                assert req.seller_note == "bap_issue_id=issue-from-bap-abc"
                # Re-call with same issue id -> existing row returned (idempotent).
                req2 = await refund_service.create_from_beckn_issue(
                    db,
                    order_beckn_id="JD-S2",
                    sub_category="ITM05",
                    reason_text="quality issue",
                    requested_amount=10000,
                    bap_issue_id="issue-from-bap-abc",
                )
                assert req2.id == req.id

        asyncio.run(run())
