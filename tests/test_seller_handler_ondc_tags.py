"""Task A2 — on_select / on_confirm handler payloads carry ONDC tags.

``handle_search`` already routes through ``BecknCatalogBuilder`` (covered
by ``test_seller_ondc_catalog_tags``). ``handle_select`` and
``handle_confirm`` build their fulfillment / payment objects inline, so
this test drives those two handlers (with lightweight stubs for the
async DB / services -- the repo has no pytest-asyncio, so we use
``asyncio.run`` + monkeypatch, matching the DB-free style of the other
seller tests) and asserts the emitted ``fulfillments`` / ``payments``
now carry the ONDC ``delivery_terms`` / ``settlement_terms`` tag groups.

Scope: tag emission only. Handler control flow is unchanged.
"""

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


class _FakeResult:
    def __init__(self, obj):
        self._obj = obj

    def scalar_one_or_none(self):
        return self._obj


class _FakeDB:
    """Minimal async-session stand-in: every execute() returns one SKU."""

    def __init__(self, sku):
        self._sku = sku

    async def execute(self, _stmt):
        return _FakeResult(self._sku)


def _sku():
    return types.SimpleNamespace(
        id=uuid.uuid4(),
        sku_code="SKU-1",
        price=Decimal("25000"),
        stock=10,
    )


_CTX = {
    "action": "select",
    "transaction_id": "t1",
    "bap_id": "beli-aman.bap.metatech.id",
}


def _tag_codes(objs):
    out = set()
    for o in objs or []:
        for t in o.get("tags") or []:
            out.add(t["code"])
    return out


class TestOnSelectTags:
    def test_fulfillment_and_payment_carry_ondc_tags(self):
        sku = _sku()
        msg = {
            "order": {
                "provider": {"id": "safiyafood.jaringan-dagang.id"},
                "items": [
                    {"id": str(sku.id), "quantity": {"selected": {"count": 2}}}
                ],
            }
        }
        resp = asyncio.run(handlers.handle_select(_CTX, msg, _FakeDB(sku)))
        order = resp["message"]["order"]
        assert "delivery_terms" in _tag_codes(order["fulfillments"])
        assert "settlement_terms" in _tag_codes(order["payments"])


class TestOnConfirmTags:
    def test_fulfillment_and_payment_carry_ondc_tags(self, monkeypatch):
        sku = _sku()
        order_id = "JD-ABC123"

        order_obj = types.SimpleNamespace(
            id=uuid.uuid4(),
            beckn_order_id=order_id,
            items=[{"sku_id": str(sku.id), "qty": 1}],
            billing_address={"name": "Budi"},
            created_at=None,
            updated_at=None,
            total=25000,
            buyer_email="budi@example.id",
            store_id=uuid.uuid4(),
            status=None,
        )

        async def _get_order(_db, _oid):
            return order_obj

        async def _decrement(_db, _items):
            return None

        async def _flush():
            return None

        async def _refresh(_obj):
            return None

        store_row = types.SimpleNamespace(
            subscriber_id="safiyafood.jaringan-dagang.id"
        )

        class _StoreResult:
            def scalar_one_or_none(self):
                return store_row

        class _ConfirmDB:
            async def execute(self, _stmt):
                return _StoreResult()

            async def flush(self):
                return None

            async def refresh(self, _o):
                return None

        payment_rec = types.SimpleNamespace(
            id=uuid.uuid4(), xendit_invoice_id="inv_1", amount=25000
        )

        async def _create_invoice(_db, _oid, _total, payer_email=None, description=None):
            return payment_rec

        monkeypatch.setattr(
            handlers.order_service, "get_order_by_beckn_id", _get_order
        )
        monkeypatch.setattr(
            handlers.inventory_service, "decrement_or_raise", _decrement
        )
        monkeypatch.setattr(
            handlers.payment_service, "create_invoice", _create_invoice
        )
        # OrderStatus is an enum used only for assignment; leave as-is.

        msg = {"order": {"id": order_id, "provider": {"id": "safiyafood"}}}
        resp = asyncio.run(handlers.handle_confirm(_CTX, msg, _ConfirmDB()))
        order = resp["message"]["order"]
        assert "delivery_terms" in _tag_codes(order["fulfillments"])
        assert "settlement_terms" in _tag_codes(order["payments"])
