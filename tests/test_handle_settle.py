"""Task A6 — Beckn /settle handler.

The handler:
  1. Validates basis / window codes (95001 on unknown).
  2. Resolves order by beckn_order_id (95002 on miss).
  3. Calls settlement_service.record_for_order and returns the wire shape.
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

from app.beckn import handlers  # noqa: E402


def _ctx(action="settle"):
    return {
        "action": action,
        "bap_id": "beli-aman.bap.jaringan-dagang.id",
        "bap_uri": "http://b",
        "bpp_id": "bpp.jaringan-dagang.id",
        "bpp_uri": "http://s",
        "transaction_id": str(uuid.uuid4()),
        "message_id": str(uuid.uuid4()),
        "timestamp": "2026-05-20T00:00:00Z",
    }


def _msg(*, order_id="JD-1", basis="DELIVERY", window="P1D"):
    return {
        "settlement": {
            "order_id": order_id,
            "settlement_basis": basis,
            "settlement_window": {"duration": window},
        }
    }


class _StubDB:
    """Minimal db stub — handle_settle only uses order_service.get_order_by_beckn_id
    and settlement_service.record_for_order (both monkeypatched below)."""

    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1


class TestHandleSettle:
    def test_unknown_basis_returns_95001(self, monkeypatch):
        async def run():
            return await handlers.handle_settle(
                _ctx(), _msg(basis="BOGUS"), _StubDB()
            )
        out = asyncio.run(run())
        assert out["error"]["code"] == "95001"
        assert "settlement_basis" in out["error"]["message"]

    def test_unknown_window_returns_95001(self):
        async def run():
            return await handlers.handle_settle(
                _ctx(), _msg(window="P30D"), _StubDB()
            )
        out = asyncio.run(run())
        assert out["error"]["code"] == "95001"

    def test_unknown_order_returns_95002(self, monkeypatch):
        from app.services import order_service

        async def _none(_db, _oid):
            return None

        monkeypatch.setattr(order_service, "get_order_by_beckn_id", _none)

        async def run():
            return await handlers.handle_settle(
                _ctx(), _msg(order_id="JD-DOES-NOT-EXIST"), _StubDB()
            )
        out = asyncio.run(run())
        assert out["error"]["code"] == "95002"

    def test_happy_path_returns_settlement_record(self, monkeypatch):
        from app.services import order_service, settlement_service

        fake_order = types.SimpleNamespace(
            id=uuid.uuid4(),
            beckn_order_id="JD-1",
        )

        async def _ord(_db, _oid):
            return fake_order

        async def _rec(_db, **kw):
            return {
                "id": str(uuid.uuid4()),
                "order_id": kw.get("order_id") and "JD-1" or "JD-1",
                "settlement_basis": kw["settlement_basis"],
                "settlement_window": {"duration": kw["settlement_window"]},
                "settlement_status": "NOT_PAID",
                "settlement_reference": None,
                "counterparties": [{
                    "type": "BPP",
                    "id": "placeholder",
                    "amount": 77000,
                    "currency": "IDR",
                }],
            }

        monkeypatch.setattr(order_service, "get_order_by_beckn_id", _ord)
        monkeypatch.setattr(settlement_service, "record_for_order", _rec)

        async def run():
            return await handlers.handle_settle(
                _ctx(), _msg(), _StubDB()
            )
        out = asyncio.run(run())
        settlement = out["message"]["settlement"]
        assert settlement["order_id"] == "JD-1"
        assert settlement["settlement_basis"] == "DELIVERY"
        assert settlement["settlement_window"]["duration"] == "P1D"
        assert settlement["settlement_status"] == "NOT_PAID"
        # Counterparty rewritten with BPP identity.
        cp = settlement["counterparties"][0]
        assert cp["type"] == "BPP"
        assert cp["amount"] == 77000
        # context.action flipped.
        assert out["context"]["action"] == "on_settle"
