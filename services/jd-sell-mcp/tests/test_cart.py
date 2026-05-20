"""``cart_add`` and ``cart_view`` tool tests."""

from __future__ import annotations

import json

import httpx
import pytest
from conftest import make_ctx, safiya_search_payload, static_bap

from tools.cart import cart_add, cart_view
from tools.search import search_products


CONV = "conv-002"


def _make_search_cart_handler(
    cart_id: str = "cart-1",
    cart_overrides: dict | None = None,
) -> callable:
    """Stitched search + cart_select + get_cart handler used by happy paths."""
    payload = safiya_search_payload("sess-1")
    base_cart = {
        "cart_id": cart_id,
        "status": "open",
        "bpp_id": "safiyafood.jaringan-dagang.id",
        "bpp_uri": "https://safiyafood.example.id",
        "provider_id": "safiya-prov-1",
        "transaction_id": "txn-1",
        "items": [{"sku_id": "SKU-1", "qty": 2}],
        "quote": {"total_idr": 130000},
        "quote_token": None,
        "billing": None,
        "shipping": None,
    }
    if cart_overrides:
        base_cart.update(cart_overrides)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/v1/search":
            return httpx.Response(200, json={
                "session_id": "sess-1",
                "transaction_id": "txn-1",
                "status": "pending",
                "bpp_id": "safiyafood.jaringan-dagang.id",
            })
        if request.url.path == "/api/v1/search/sess-1/results":
            return httpx.Response(200, json=payload)
        if request.method == "POST" and request.url.path == "/api/v1/cart/select":
            return httpx.Response(200, json={
                "cart_id": cart_id,
                "transaction_id": "txn-1",
                "status": "open",
            })
        if request.method == "GET" and request.url.path == f"/api/v1/cart/{cart_id}":
            return httpx.Response(200, json=base_cart)
        return httpx.Response(404, json={"detail": str(request.url)})
    return handler


@pytest.mark.asyncio
async def test_cart_add_happy_path_after_search(state_store):
    handler = _make_search_cart_handler()
    ctx = make_ctx(handler, state_store)

    await search_products(ctx, {"conversation_id": CONV, "query": "rendang"})
    result = await cart_add(ctx, {
        "conversation_id": CONV,
        "items": [{"item_id": "SKU-1", "qty": 2}],
    })

    assert not result.is_error
    text = result.content[0]["text"]
    assert "SKU-1" in text
    assert "Rp 130.000" in text
    data = json.loads(text.split("```json\n", 1)[1].split("\n```", 1)[0])
    assert data["cart_id"] == "cart-1"

    # State now has cart_id.
    state = await state_store.get(CONV)
    assert state["cart_id"] == "cart-1"


@pytest.mark.asyncio
async def test_cart_add_without_prior_search_friendly_error(state_store):
    handler = static_bap({})
    ctx = make_ctx(handler, state_store)
    result = await cart_add(ctx, {
        "conversation_id": "fresh-conv",
        "items": [{"item_id": "SKU-1", "qty": 1}],
    })
    assert result.is_error
    assert "Belum ada konteks" in result.content[0]["text"]


@pytest.mark.asyncio
async def test_cart_view_happy_path(state_store):
    handler = _make_search_cart_handler()
    ctx = make_ctx(handler, state_store)
    await search_products(ctx, {"conversation_id": CONV, "query": "rendang"})
    await cart_add(ctx, {
        "conversation_id": CONV,
        "items": [{"item_id": "SKU-1", "qty": 2}],
    })

    result = await cart_view(ctx, {"conversation_id": CONV})
    assert not result.is_error
    assert "SKU-1" in result.content[0]["text"]


@pytest.mark.asyncio
async def test_cart_view_without_cart_friendly_error(state_store):
    handler = static_bap({})
    ctx = make_ctx(handler, state_store)
    result = await cart_view(ctx, {"conversation_id": "nope"})
    assert result.is_error
    assert "Belum ada keranjang aktif" in result.content[0]["text"]


@pytest.mark.asyncio
async def test_cart_add_410_expired(state_store):
    """If the BAP rejects with 410 (cart expired), surface Indonesian copy."""
    payload = safiya_search_payload("sess-x")

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST" and req.url.path == "/api/v1/search":
            return httpx.Response(200, json={
                "session_id": "sess-x", "transaction_id": "t", "status": "pending",
                "bpp_id": "safiyafood.jaringan-dagang.id",
            })
        if req.url.path == "/api/v1/search/sess-x/results":
            return httpx.Response(200, json=payload)
        if req.method == "POST" and req.url.path == "/api/v1/cart/select":
            return httpx.Response(410, json={"detail": "expired"})
        return httpx.Response(404)

    ctx = make_ctx(handler, state_store)
    await search_products(ctx, {"conversation_id": CONV, "query": "rendang"})
    result = await cart_add(ctx, {
        "conversation_id": CONV,
        "items": [{"item_id": "SKU-1", "qty": 1}],
    })
    assert result.is_error
    assert "kedaluwarsa" in result.content[0]["text"]
