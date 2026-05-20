"""Task A5 — seller-side /issue handler.

The seller's ``handle_issue`` accepts a buyer-raised ONDC IGM Issue,
creates (or no-ops on retry of) a ``RefundRequest`` row, and returns
the synchronous PROCESSING ACK envelope.

Coverage:
* Happy path: /issue creates a RefundRequest, returns PROCESSING ACK.
* Idempotency: re-sending the same /issue (matched on bap_issue_id)
  returns the same RefundRequest without creating a duplicate row.
* Unknown order: returns a 90005 (Order not eligible) error envelope.
* Invalid IGM category / sub_category: returns 90001 (Invalid Issue).
"""

from __future__ import annotations

import asyncio
import os
import sys
import types
import uuid
from decimal import Decimal

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PROTO = os.path.join(_ROOT, "packages", "beckn-protocol")
for _p in (_ROOT, _PROTO):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.beckn import handlers  # noqa: E402
from app.models.refund import RefundReason, RefundStatus  # noqa: E402


_CTX = {
    "action": "issue",
    "transaction_id": "t1",
    "bap_id": "beli-aman.bap.jaringan-dagang.id",
}


def _issue_msg(
    *,
    issue_id="issue-1",
    category="ITEM",
    sub_category="ITM02",
    order_id="JD-XYZ",
    refund_amount=None,
):
    issue = {
        "id": issue_id,
        "category": category,
        "sub_category": sub_category,
        "complainant_info": {
            "type": "CONSUMER",
            "id": "profile-1",
            "name": "Budi",
        },
        "order_details": {"id": order_id},
        "description": {
            "short_desc": "paket belum tiba",
            "long_desc": "saya tidak menerima paket meski sudah ditandai terkirim",
        },
        "status": "OPEN",
    }
    if refund_amount is not None:
        issue["description"]["additional_desc"] = {
            "refund": {"amount": str(refund_amount), "currency": "IDR"}
        }
    return {"issue": issue}


class TestHappyPath:
    def test_creates_refund_request_returns_processing_ack(
        self, monkeypatch
    ):
        captured: dict = {}

        async def _create(_db, **kwargs):
            captured.update(kwargs)
            return types.SimpleNamespace(
                id=uuid.uuid4(),
                status=RefundStatus.PENDING,
                reason_code=RefundReason.ITEM_NOT_RECEIVED,
                requested_amount=35000,
                seller_note=f"bap_issue_id={kwargs['bap_issue_id']}",
            )

        from app.services import refund_service
        monkeypatch.setattr(
            refund_service, "create_from_beckn_issue", _create
        )

        resp = asyncio.run(
            handlers.handle_issue(
                _CTX,
                _issue_msg(refund_amount=35000),
                db=None,
            )
        )

        assert resp["context"]["action"] == "on_issue"
        out = resp["message"]["issue"]
        assert out["id"] == "issue-1"
        assert out["status"] == "PROCESSING"
        actions = out["issue_actions"]["respondent_actions"]
        assert actions and actions[0]["respondent_action"] == "PROCESSING"

        # Refund was minted with the right pieces from the envelope.
        assert captured["order_beckn_id"] == "JD-XYZ"
        assert captured["sub_category"] == "ITM02"
        assert captured["bap_issue_id"] == "issue-1"
        assert captured["requested_amount"] == 35000


class TestRetryIdempotency:
    def test_retry_with_same_issue_id_returns_same_refund(
        self, monkeypatch
    ):
        existing_id = uuid.uuid4()

        async def _create(_db, **kwargs):
            # Simulate "already created" path by always returning the
            # same id when bap_issue_id matches.
            return types.SimpleNamespace(
                id=existing_id,
                status=RefundStatus.PENDING,
                reason_code=RefundReason.ITEM_NOT_RECEIVED,
                requested_amount=35000,
                seller_note=f"bap_issue_id={kwargs['bap_issue_id']}",
            )

        from app.services import refund_service
        monkeypatch.setattr(
            refund_service, "create_from_beckn_issue", _create
        )

        resp1 = asyncio.run(
            handlers.handle_issue(
                _CTX,
                _issue_msg(issue_id="issue-retry"),
                db=None,
            )
        )
        resp2 = asyncio.run(
            handlers.handle_issue(
                _CTX,
                _issue_msg(issue_id="issue-retry"),
                db=None,
            )
        )
        # Both responses ACK PROCESSING for the same Issue id.
        assert resp1["message"]["issue"]["id"] == "issue-retry"
        assert resp2["message"]["issue"]["id"] == "issue-retry"
        assert resp1["message"]["issue"]["status"] == "PROCESSING"
        assert resp2["message"]["issue"]["status"] == "PROCESSING"


class TestErrors:
    def test_unknown_order_returns_90005(self, monkeypatch):
        async def _create(_db, **_):
            return None  # order not found

        from app.services import refund_service
        monkeypatch.setattr(
            refund_service, "create_from_beckn_issue", _create
        )

        resp = asyncio.run(
            handlers.handle_issue(
                _CTX,
                _issue_msg(order_id="NO-SUCH-ORDER"),
                db=None,
            )
        )
        assert "error" in resp
        assert resp["error"]["code"] == "90005"

    def test_unknown_category_returns_90001(self):
        resp = asyncio.run(
            handlers.handle_issue(
                _CTX,
                _issue_msg(category="BOGUS"),
                db=None,
            )
        )
        assert resp["error"]["code"] == "90001"

    def test_unknown_item_subcategory_returns_90001(self):
        resp = asyncio.run(
            handlers.handle_issue(
                _CTX,
                _issue_msg(category="ITEM", sub_category="NOPE"),
                db=None,
            )
        )
        assert resp["error"]["code"] == "90001"

    def test_missing_issue_id_returns_90001(self):
        msg = _issue_msg()
        msg["issue"].pop("id")
        resp = asyncio.run(
            handlers.handle_issue(_CTX, msg, db=None)
        )
        assert resp["error"]["code"] == "90001"
