"""Task A4 — /on_init carries a quote_token tag; /on_confirm carries the
Xendit invoice/QR URL in payments[].params.

Mirrors the DB-free monkeypatch style of ``test_seller_handler_ondc_tags``:
we stub out order_service / inventory_service / payment_service so the
handler's pure assembly logic can be exercised without a real DB.
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
from app.beckn.quote_token import verify_quote_token  # noqa: E402


_CTX = {
    "action": "init",
    "transaction_id": "t1",
    "bap_id": "beli-aman.bap.jaringan-dagang.id",
}


def _sku(stock=10, price=25000):
    return types.SimpleNamespace(
        id=uuid.uuid4(),
        sku_code="SKU-1",
        price=Decimal(str(price)),
        stock=stock,
    )


class _FakeResult:
    def __init__(self, obj):
        self._obj = obj

    def scalar_one_or_none(self):
        return self._obj


class _FakeInitDB:
    """Returns a Store, then a SKU. handle_init calls
    _get_default_store (one .execute) and then per-item .execute lookups."""

    def __init__(self, store, sku):
        self.store = store
        self.sku = sku
        self.calls = 0

    async def execute(self, _stmt):
        self.calls += 1
        # The first execute() is _get_default_store; subsequent ones are SKU lookups.
        if self.calls == 1:
            return _FakeResult(self.store)
        return _FakeResult(self.sku)

    async def flush(self):
        return None


class TestOnInitQuoteToken:
    def test_on_init_emits_quote_token_tag(self, monkeypatch):
        store = types.SimpleNamespace(
            id=uuid.uuid4(),
            subscriber_id="safiyafood.jaringan-dagang.id",
        )
        sku = _sku()

        async def _create_order(_db, _store_id, _data):
            return types.SimpleNamespace(
                id=uuid.uuid4(), beckn_order_id="JD-ABCDEF",
            )

        monkeypatch.setattr(handlers.order_service, "create_order", _create_order)

        msg = {
            "order": {
                "provider": {"id": "safiyafood.jaringan-dagang.id"},
                "billing": {"name": "Budi", "email": "b@b.id"},
                "fulfillments": [
                    {
                        "type": "Delivery",
                        "end": {"location": {"address": {"city": "Jakarta"}}},
                    }
                ],
                "items": [
                    {"id": str(sku.id), "quantity": {"selected": {"count": 2}}},
                ],
            }
        }
        resp = asyncio.run(handlers.handle_init(_CTX, msg, _FakeInitDB(store, sku)))
        order = resp["message"]["order"]
        tags = order.get("tags") or []
        codes = {t.get("code") for t in tags}
        assert "quote_token" in codes
        # And it verifies (signature + TTL) using our shared HMAC secret.
        token_tag = next(t for t in tags if t.get("code") == "quote_token")
        token_val = token_tag["list"][0]["value"]
        ok, err = verify_quote_token(token_val)
        assert ok, err

    def test_on_init_quote_token_matches_items_and_total(self, monkeypatch):
        store = types.SimpleNamespace(
            id=uuid.uuid4(),
            subscriber_id="safiyafood.jaringan-dagang.id",
        )
        sku = _sku(price=10000)  # 10000 * 2 + 15000 shipping = 35000

        async def _create_order(_db, _store_id, _data):
            return types.SimpleNamespace(
                id=uuid.uuid4(), beckn_order_id="JD-MATCH",
            )

        monkeypatch.setattr(handlers.order_service, "create_order", _create_order)

        msg = {
            "order": {
                "provider": {"id": "safiyafood.jaringan-dagang.id"},
                "billing": {"name": "Sari"},
                "fulfillments": [
                    {"type": "Delivery", "end": {"location": {"address": {}}}}
                ],
                "items": [
                    {"id": str(sku.id), "quantity": {"selected": {"count": 2}}},
                ],
            }
        }
        resp = asyncio.run(handlers.handle_init(_CTX, msg, _FakeInitDB(store, sku)))
        order = resp["message"]["order"]
        token = next(
            t for t in order["tags"] if t.get("code") == "quote_token"
        )["list"][0]["value"]

        # The token must verify against the exact same (items, total) the
        # handler computed: 2*10000 + 15000 flat shipping = 35000.
        ok, err = verify_quote_token(
            token,
            items=[{"sku_id": str(sku.id), "qty": 2}],
            total=35000,
        )
        assert ok, err


class TestOnConfirmInvoiceUrl:
    def test_on_confirm_surfaces_invoice_url(self, monkeypatch):
        sku = _sku()
        order_id_str = "JD-CONFIRM"

        order_obj = types.SimpleNamespace(
            id=uuid.uuid4(),
            beckn_order_id=order_id_str,
            items=[{"sku_id": str(sku.id), "qty": 1}],
            billing_address={"name": "Budi"},
            created_at=None,
            updated_at=None,
            total=25000,
            buyer_email="budi@example.id",
            store_id=uuid.uuid4(),
            status=None,
        )
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

        async def _get_order(_db, _oid):
            return order_obj

        async def _decrement(_db, _items):
            return None

        payment_rec = types.SimpleNamespace(
            id=uuid.uuid4(),
            xendit_invoice_id="inv_42",
            xendit_invoice_url="https://checkout.xendit.co/web/inv_42",
            amount=25000,
        )

        async def _create_invoice(_db, _oid, _total, payer_email=None, description=None):
            return payment_rec

        monkeypatch.setattr(handlers.order_service, "get_order_by_beckn_id", _get_order)
        monkeypatch.setattr(handlers.inventory_service, "decrement_or_raise", _decrement)
        monkeypatch.setattr(handlers.payment_service, "create_invoice", _create_invoice)

        msg = {"order": {"id": order_id_str, "provider": {"id": "safiyafood"}}}
        resp = asyncio.run(handlers.handle_confirm(_CTX, msg, _ConfirmDB()))
        order = resp["message"]["order"]
        params = order["payments"][0]["params"]
        assert params.get("invoice_url") == "https://checkout.xendit.co/web/inv_42"
        # QR landing URL reuses the same Xendit hosted page.
        assert params.get("qr_image_url") == "https://checkout.xendit.co/web/inv_42"

    def test_on_confirm_without_invoice_url_omits_field(self, monkeypatch):
        """When the payment record has no invoice_url (e.g. dev/sandbox),
        the response omits invoice_url + qr_image_url cleanly (no None
        values that the BAP would then have to special-case)."""
        sku = _sku()
        order_id_str = "JD-NO-INV"
        order_obj = types.SimpleNamespace(
            id=uuid.uuid4(), beckn_order_id=order_id_str,
            items=[{"sku_id": str(sku.id), "qty": 1}],
            billing_address={"name": "Sari"},
            created_at=None, updated_at=None,
            total=25000, buyer_email=None,
            store_id=uuid.uuid4(), status=None,
        )
        store_row = types.SimpleNamespace(subscriber_id="safiyafood.jaringan-dagang.id")

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

        async def _get_order(_db, _oid):
            return order_obj

        async def _decrement(_db, _items):
            return None

        payment_rec = types.SimpleNamespace(
            id=uuid.uuid4(),
            xendit_invoice_id="dev-xyz",
            xendit_invoice_url=None,  # no hosted URL in dev mode
            amount=25000,
        )

        async def _create_invoice(_db, _oid, _total, payer_email=None, description=None):
            return payment_rec

        monkeypatch.setattr(handlers.order_service, "get_order_by_beckn_id", _get_order)
        monkeypatch.setattr(handlers.inventory_service, "decrement_or_raise", _decrement)
        monkeypatch.setattr(handlers.payment_service, "create_invoice", _create_invoice)

        msg = {"order": {"id": order_id_str}}
        resp = asyncio.run(handlers.handle_confirm(_CTX, msg, _ConfirmDB()))
        params = resp["message"]["order"]["payments"][0]["params"]
        assert "invoice_url" not in params
        assert "qr_image_url" not in params
