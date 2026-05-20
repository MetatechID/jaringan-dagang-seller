"""``search_products`` and ``get_product`` tool tests."""

from __future__ import annotations

import json

import httpx
import pytest
from conftest import (
    make_bap_client,
    make_ctx,
    safiya_search_payload,
    static_bap,
)

from tools.search import get_product, search_products


CONV = "conv-001"


@pytest.mark.asyncio
async def test_search_happy_path(state_store):
    """POST /search → GET /results returns markdown + JSON; state updated."""
    payload = safiya_search_payload("sess-42")
    handler = static_bap({
        ("POST", "/api/v1/search"): {
            "session_id": "sess-42",
            "transaction_id": "txn-42",
            "status": "pending",
            "bpp_id": "safiyafood.jaringan-dagang.id",
        },
        ("GET", "/api/v1/search/sess-42/results"): payload,
    })
    ctx = make_ctx(handler, state_store)

    result = await search_products(
        ctx, {"conversation_id": CONV, "query": "rendang"}
    )
    assert not result.is_error
    text = result.content[0]["text"]
    assert "Rendang Sapi 200g" in text
    assert "Rp 65.000" in text  # IDR formatter applied
    # JSON block is present and parseable.
    block = text.split("```json\n", 1)[1].split("\n```", 1)[0]
    data = json.loads(block)
    assert data["session_id"] == "sess-42"
    assert data["bpp_id"] == "safiyafood.jaringan-dagang.id"
    assert data["result_count"] == 2

    # State persisted.
    state = await state_store.get(CONV)
    assert state is not None
    assert state["session_id"] == "sess-42"
    assert state["bpp_id"] == "safiyafood.jaringan-dagang.id"
    assert state["transaction_id"] == "txn-42"

    # Cache populated for get_product lookups.
    cache = ctx.search_cache[CONV]
    assert "PROD-1" in cache["index"]
    assert "SKU-1" in cache["index"]


@pytest.mark.asyncio
async def test_search_401_returns_indonesian_error(state_store):
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "bad token"})
    ctx = make_ctx(handler, state_store)
    result = await search_products(ctx, {"conversation_id": CONV, "query": "x"})
    assert result.is_error
    text = result.content[0]["text"]
    assert "tidak punya akses" in text
    assert "401" in text


@pytest.mark.asyncio
async def test_search_5xx_friendly_error(state_store):
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "boom"})
    ctx = make_ctx(handler, state_store)
    result = await search_products(ctx, {"conversation_id": CONV, "query": "x"})
    assert result.is_error
    assert "Sistem sedang sibuk" in result.content[0]["text"]


@pytest.mark.asyncio
async def test_search_timeout_friendly_error(state_store):
    """httpx raises TimeoutException → BAPClient wraps to BAPTransportError → friendly copy."""
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated read timeout", request=request)
    ctx = make_ctx(timeout_handler, state_store)
    result = await search_products(ctx, {"conversation_id": CONV, "query": "x"})
    assert result.is_error
    assert "Sistem sedang sibuk" in result.content[0]["text"]


@pytest.mark.asyncio
async def test_search_polls_until_results_available(state_store):
    """First /results call returns empty pending; second returns results."""
    poll_counter = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/v1/search":
            return httpx.Response(200, json={
                "session_id": "sess-99",
                "transaction_id": "txn-99",
                "status": "pending",
            })
        if request.url.path == "/api/v1/search/sess-99/results":
            poll_counter["n"] += 1
            if poll_counter["n"] < 3:
                return httpx.Response(200, json={
                    "session_id": "sess-99",
                    "status": "pending",
                    "results": [],
                })
            return httpx.Response(200, json=safiya_search_payload("sess-99"))
        return httpx.Response(404)

    ctx = make_ctx(handler, state_store)
    result = await search_products(
        ctx, {"conversation_id": CONV, "query": "rendang"}
    )
    assert not result.is_error
    assert "Rendang Sapi" in result.content[0]["text"]
    assert poll_counter["n"] >= 3


@pytest.mark.asyncio
async def test_get_product_hits_cache_no_http(state_store):
    """get_product must NOT call BAP — it reads the search cache."""
    payload = safiya_search_payload("sess-42")
    handler = static_bap({
        ("POST", "/api/v1/search"): {
            "session_id": "sess-42",
            "transaction_id": "txn-42",
            "status": "pending",
        },
        ("GET", "/api/v1/search/sess-42/results"): payload,
    })
    ctx = make_ctx(handler, state_store)
    await search_products(ctx, {"conversation_id": CONV, "query": "rendang"})

    # Build a NEW client that 500s every request so we can prove the second
    # tool call never goes to the network.
    def explode(req: httpx.Request) -> httpx.Response:
        raise AssertionError(f"get_product must not hit BAP, but got {req}")

    ctx.bap = make_bap_client(explode)
    result = await get_product(
        ctx, {"conversation_id": CONV, "item_id": "PROD-1"}
    )
    assert not result.is_error
    text = result.content[0]["text"]
    assert "Rendang Sapi 200g" in text


@pytest.mark.asyncio
async def test_get_product_no_cache_returns_friendly_error(state_store):
    handler = static_bap({})
    ctx = make_ctx(handler, state_store)
    result = await get_product(
        ctx, {"conversation_id": CONV, "item_id": "anything"}
    )
    assert result.is_error
    assert "Belum ada konteks" in result.content[0]["text"]


@pytest.mark.asyncio
async def test_get_product_unknown_id(state_store):
    payload = safiya_search_payload("sess-42")
    handler = static_bap({
        ("POST", "/api/v1/search"): {
            "session_id": "sess-42",
            "transaction_id": "txn-42",
            "status": "pending",
        },
        ("GET", "/api/v1/search/sess-42/results"): payload,
    })
    ctx = make_ctx(handler, state_store)
    await search_products(ctx, {"conversation_id": CONV, "query": "rendang"})

    result = await get_product(
        ctx, {"conversation_id": CONV, "item_id": "DOES-NOT-EXIST"}
    )
    assert result.is_error
    assert "DOES-NOT-EXIST" in result.content[0]["text"]
