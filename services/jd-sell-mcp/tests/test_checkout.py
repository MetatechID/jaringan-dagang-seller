"""``start_checkout`` and ``payment_status`` tool tests."""

from __future__ import annotations

import json

import httpx
import pytest
from conftest import make_ctx, safiya_search_payload, static_bap

from tools.cart import cart_add
from tools.checkout import payment_status, start_checkout
from tools.search import search_products


CONV = "conv-003"

BILLING = {"name": "Andi", "email": "andi@example.com", "phone": "+6281112223333"}
SHIPPING = {
    "address": "Jl. Sudirman No. 1",
    "city": "Jakarta",
    "postal_code": "10220",
    "recipient_name": "Andi",
    "recipient_phone": "+6281112223333",
}


def _stitched_handler(*, payment_state_seq: list[str] | None = None):
    """Walks through search → cart → checkout → status; payment_state_seq
    is consumed one item per /status call.
    """
    states = list(payment_state_seq or ["pending"])
    payload = safiya_search_payload("sess-c")
    cart_body = {
        "cart_id": "cart-c",
        "status": "open",
        "bpp_id": "safiyafood.jaringan-dagang.id",
        "bpp_uri": "https://safiyafood.example.id",
        "provider_id": "safiya-prov-1",
        "transaction_id": "txn-c",
        "items": [{"sku_id": "SKU-1", "qty": 1}],
        "quote": {"total_idr": 65000},
        "quote_token": None,
        "billing": None,
        "shipping": None,
    }
    seen = {"init_calls": 0, "confirm_calls": 0, "status_calls": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        p = req.url.path
        m = req.method
        if m == "POST" and p == "/api/v1/search":
            return httpx.Response(200, json={
                "session_id": "sess-c", "transaction_id": "txn-c",
                "status": "pending", "bpp_id": "safiyafood.jaringan-dagang.id",
            })
        if p == "/api/v1/search/sess-c/results":
            return httpx.Response(200, json=payload)
        if m == "POST" and p == "/api/v1/cart/select":
            return httpx.Response(200, json={
                "cart_id": "cart-c", "transaction_id": "txn-c", "status": "open",
            })
        if m == "GET" and p == "/api/v1/cart/cart-c":
            return httpx.Response(200, json=cart_body)
        if m == "POST" and p == "/api/v1/cart/cart-c/init":
            seen["init_calls"] += 1
            return httpx.Response(200, json={
                "cart_id": "cart-c", "status": "drafted",
                "quote_token": "qt-abc",
            })
        if m == "POST" and p == "/api/v1/checkout/cart-c/confirm":
            seen["confirm_calls"] += 1
            return httpx.Response(200, json={
                "cart_id": "cart-c",
                "order_id": "ord-xyz",
                "status": "confirmed",
                "payment": {
                    "qr_image_url": "https://xendit.example/qr.png",
                    "invoice_url": "https://xendit.example/inv",
                    "expires_at": "2026-05-21T00:00:00Z",
                },
            })
        if m == "GET" and p == "/api/v1/checkout/cart-c/status":
            cur = states[seen["status_calls"]] if seen["status_calls"] < len(states) else states[-1]
            seen["status_calls"] += 1
            return httpx.Response(200, json={
                "cart_id": "cart-c",
                "order_id": "ord-xyz",
                "payment_state": cur,
                "status": "confirmed",
            })
        return httpx.Response(404, json={"detail": str(req.url)})

    return handler, seen


@pytest.mark.asyncio
async def test_start_checkout_end_to_end(state_store):
    handler, seen = _stitched_handler()
    ctx = make_ctx(handler, state_store)
    await search_products(ctx, {"conversation_id": CONV, "query": "rendang"})
    await cart_add(ctx, {
        "conversation_id": CONV,
        "items": [{"item_id": "SKU-1", "qty": 1}],
    })

    result = await start_checkout(ctx, {
        "conversation_id": CONV, "billing": BILLING, "shipping": SHIPPING,
    })
    assert not result.is_error
    text = result.content[0]["text"]
    assert "qr.png" in text
    assert "ord-xyz" in text
    data = json.loads(text.split("```json\n", 1)[1].split("\n```", 1)[0])
    assert data["order_id"] == "ord-xyz"
    assert seen["init_calls"] == 1
    assert seen["confirm_calls"] == 1

    state = await state_store.get(CONV)
    assert state["billing"] == BILLING
    assert state["shipping"] == SHIPPING


@pytest.mark.asyncio
async def test_start_checkout_without_cart_friendly_error(state_store):
    handler = static_bap({})
    ctx = make_ctx(handler, state_store)
    result = await start_checkout(ctx, {
        "conversation_id": "no-cart", "billing": BILLING, "shipping": SHIPPING,
    })
    assert result.is_error
    assert "Belum ada keranjang aktif" in result.content[0]["text"]


@pytest.mark.asyncio
async def test_payment_status_pending_then_paid(state_store):
    handler, seen = _stitched_handler(payment_state_seq=["pending", "pending", "paid"])
    ctx = make_ctx(handler, state_store)
    await search_products(ctx, {"conversation_id": CONV, "query": "rendang"})
    await cart_add(ctx, {
        "conversation_id": CONV,
        "items": [{"item_id": "SKU-1", "qty": 1}],
    })
    await start_checkout(ctx, {
        "conversation_id": CONV, "billing": BILLING, "shipping": SHIPPING,
    })

    r1 = await payment_status(ctx, {"conversation_id": CONV})
    assert "belum masuk" in r1.content[0]["text"].lower()
    r2 = await payment_status(ctx, {"conversation_id": CONV})
    assert "belum masuk" in r2.content[0]["text"].lower()
    r3 = await payment_status(ctx, {"conversation_id": CONV})
    assert "sudah masuk" in r3.content[0]["text"].lower()
    assert seen["status_calls"] == 3


@pytest.mark.asyncio
async def test_payment_status_without_cart_friendly_error(state_store):
    handler = static_bap({})
    ctx = make_ctx(handler, state_store)
    result = await payment_status(ctx, {"conversation_id": "nope"})
    assert result.is_error
    assert "Belum ada pesanan" in result.content[0]["text"]


@pytest.mark.asyncio
async def test_start_checkout_401_from_bap(state_store):
    """Auth failure during /init must surface friendly Indonesian copy."""
    handler, _ = _stitched_handler()

    def auth_failing(req: httpx.Request) -> httpx.Response:
        p = req.url.path
        if req.method == "POST" and p == "/api/v1/cart/cart-c/init":
            return httpx.Response(401, json={"detail": "bad token"})
        return handler(req)

    ctx = make_ctx(auth_failing, state_store)
    await search_products(ctx, {"conversation_id": CONV, "query": "rendang"})
    await cart_add(ctx, {
        "conversation_id": CONV,
        "items": [{"item_id": "SKU-1", "qty": 1}],
    })
    result = await start_checkout(ctx, {
        "conversation_id": CONV, "billing": BILLING, "shipping": SHIPPING,
    })
    assert result.is_error
    assert "tidak punya akses" in result.content[0]["text"]
