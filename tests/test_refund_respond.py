"""Task A5 — refund_service.respond_to_issue (ONDC IGM /on_issue).

The seller agent's response path: take a PENDING RefundRequest and
emit a /on_issue back to the BAP. We exercise the three actions —
PROCESSING (no state change), RESOLVED (Xendit mock + state flip),
REJECTED (DENIED + reason note).

The actual /on_issue HTTP send is mocked via monkeypatching the
``app.beckn.callback_sender.send_callback`` import that
``_emit_on_issue`` performs lazily.
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

from app.models.order import EscrowStatus  # noqa: E402
from app.models.payment import PaymentStatus  # noqa: E402
from app.models.refund import (  # noqa: E402
    RefundReason,
    RefundRequest,
    RefundStatus,
)
from app.services import refund_service  # noqa: E402


def _refund(*, status=RefundStatus.PENDING, bap_issue_id="issue-A"):
    return types.SimpleNamespace(
        id=uuid.uuid4(),
        order_id=uuid.uuid4(),
        requested_by="buyer",
        reason_code=RefundReason.ITEM_NOT_RECEIVED,
        reason_text="paket belum tiba",
        requested_amount=35000,
        status=status,
        seller_note=f"bap_issue_id={bap_issue_id}",
        decided_at=None,
        decided_by=None,
        xendit_refund_id=None,
        error=None,
        created_at=None,
        updated_at=None,
    )


def _order():
    return types.SimpleNamespace(
        id=uuid.uuid4(),
        beckn_order_id="JD-X",
        bap_id="beli-aman.bap.jaringan-dagang.id",
        total=35000,
        escrow_status=EscrowStatus.HELD if hasattr(EscrowStatus, "HELD") else None,
    )


def _payment():
    return types.SimpleNamespace(
        order_id=None,
        xendit_invoice_id="inv_1",
        status=PaymentStatus.PAID if hasattr(PaymentStatus, "PAID") else None,
    )


class _Result:
    def __init__(self, obj):
        self._obj = obj

    def scalar_one_or_none(self):
        return self._obj


class _FakeDB:
    """In-memory AsyncSession stand-in.

    get(model, id):
      first call -> the RefundRequest we registered
      subsequent calls -> the Order
    execute(stmt):
      returns the payment we registered (used by refund_service for
      PaymentRecord lookup) — we just return whatever fixture is set.
    """

    def __init__(self, req, order, payment):
        self.req = req
        self.order = order
        self.payment = payment
        self.commits = 0

    async def get(self, model, _i):
        # Hand back RefundRequest on first ask, Order on second+
        from app.models.order import Order as _Order
        from app.models.refund import RefundRequest as _RR
        if model is _RR:
            return self.req
        if model is _Order:
            return self.order
        return None

    async def execute(self, _stmt):
        return _Result(self.payment)

    async def commit(self):
        self.commits += 1

    async def refresh(self, _o):
        return None


@pytest.fixture(autouse=True)
def _patch_send_callback(monkeypatch):
    """Stub the outbound /on_issue HTTP so tests stay local."""

    captured: list[dict] = []

    async def _send(**kwargs):
        captured.append(kwargs)
        return True

    # The import inside _emit_on_issue is `from app.beckn.callback_sender
    # import load_bpp_signing_key_b64, send_callback` — patch both.
    import app.beckn.callback_sender as cb

    monkeypatch.setattr(cb, "send_callback", _send)
    monkeypatch.setattr(cb, "load_bpp_signing_key_b64", lambda: None)

    # Also nuke Xendit so RESOLVED stays in mock mode.
    from app.config import settings
    monkeypatch.setattr(settings, "XENDIT_SECRET_KEY", "", raising=False)

    return captured


class TestProcessingResponse:
    def test_processing_emits_on_issue_no_state_change(
        self, _patch_send_callback
    ):
        req = _refund()
        db = _FakeDB(req, _order(), _payment())

        res = asyncio.run(
            refund_service.respond_to_issue(
                db,
                req.id,
                action="PROCESSING",
                note="Investigating; will respond within 24h.",
            )
        )
        # Still PENDING (no terminal flip).
        assert res.status == RefundStatus.PENDING
        # Outbound /on_issue emitted.
        assert _patch_send_callback, "send_callback should have fired"
        sent = _patch_send_callback[-1]
        assert sent["action"] == "on_issue"
        env = sent["response_body"]
        actions = env["message"]["issue"]["issue_actions"][
            "respondent_actions"
        ]
        assert actions[-1]["respondent_action"] == "PROCESSING"


class TestResolvedResponse:
    def test_resolved_flips_to_refunded_and_emits(
        self, _patch_send_callback
    ):
        req = _refund()
        db = _FakeDB(req, _order(), _payment())

        res = asyncio.run(
            refund_service.respond_to_issue(
                db,
                req.id,
                action="RESOLVED",
                note="Refund issued via Xendit.",
            )
        )
        # Mock-mode Xendit means we synthesized a refund id + flipped to
        # REFUNDED in one call.
        assert res.status == RefundStatus.REFUNDED
        assert res.xendit_refund_id and res.xendit_refund_id.startswith(
            "mock-refund-"
        )
        # Outbound /on_issue carries RESOLVED + the refund amount.
        sent = _patch_send_callback[-1]
        env = sent["response_body"]
        issue = env["message"]["issue"]
        actions = issue["issue_actions"]["respondent_actions"]
        assert actions[-1]["respondent_action"] == "RESOLVED"
        assert issue["resolution"]["refund_amount"]["value"] == "35000"
        assert issue["resolution"]["refund_amount"]["currency"] == "IDR"


class TestRejectedResponse:
    def test_rejected_marks_denied_with_reason_note(
        self, _patch_send_callback
    ):
        req = _refund()
        db = _FakeDB(req, _order(), _payment())

        res = asyncio.run(
            refund_service.respond_to_issue(
                db,
                req.id,
                action="REJECTED",
                note="Item delivered; tracking confirms signature receipt.",
            )
        )
        assert res.status == RefundStatus.DENIED
        # Outbound /on_issue carries REJECTED + reason in long_desc.
        sent = _patch_send_callback[-1]
        env = sent["response_body"]
        issue = env["message"]["issue"]
        actions = issue["issue_actions"]["respondent_actions"]
        assert actions[-1]["respondent_action"] == "REJECTED"
        assert issue["resolution"]["action_triggered"] == "REJECTED"


class TestValidation:
    def test_unknown_action_raises_refund_error(self):
        req = _refund()
        db = _FakeDB(req, _order(), _payment())
        with pytest.raises(refund_service.RefundError):
            asyncio.run(
                refund_service.respond_to_issue(
                    db, req.id, action="ESCALATE",
                )
            )

    def test_cannot_reject_an_already_refunded_request(self):
        req = _refund(status=RefundStatus.REFUNDED)
        db = _FakeDB(req, _order(), _payment())
        with pytest.raises(refund_service.RefundError):
            asyncio.run(
                refund_service.respond_to_issue(
                    db, req.id, action="REJECTED",
                )
            )

    def test_extract_bap_issue_id_round_trip(self):
        req = _refund(bap_issue_id="round-trip-1")
        assert (
            refund_service._extract_bap_issue_id(req) == "round-trip-1"
        )

    def test_unknown_refund_id_raises(self):
        # If db.get returns None, RefundError must be raised.
        class _MissingDB(_FakeDB):
            async def get(self, _m, _i):
                return None

        db = _MissingDB(None, None, None)
        with pytest.raises(refund_service.RefundError):
            asyncio.run(
                refund_service.respond_to_issue(
                    db, uuid.uuid4(), action="RESOLVED",
                )
            )
