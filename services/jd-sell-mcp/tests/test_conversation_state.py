"""SQLite-backed conversation_state persistence + isolation."""

from __future__ import annotations

import asyncio
import os

import pytest
from conftest import make_ctx, safiya_search_payload, static_bap

from lib.conversation_state import ConversationStateStore
from tools.cart import cart_add
from tools.search import search_products


@pytest.mark.asyncio
async def test_persistence_across_store_instances(tmp_path, monkeypatch):
    """A second store opening the same path sees prior data."""
    db = str(tmp_path / "s.db")
    monkeypatch.setenv("STATE_DB_PATH", db)
    store1 = ConversationStateStore()
    await store1.upsert(
        "conv-X",
        session_id="sess-X",
        bpp_id="safiyafood.jaringan-dagang.id",
        cart_id="cart-X",
    )

    store2 = ConversationStateStore()
    row = await store2.get("conv-X")
    assert row is not None
    assert row["session_id"] == "sess-X"
    assert row["cart_id"] == "cart-X"


@pytest.mark.asyncio
async def test_isolation_between_conversations(tmp_path, monkeypatch):
    monkeypatch.setenv("STATE_DB_PATH", str(tmp_path / "iso.db"))
    store = ConversationStateStore()
    await store.upsert("A", session_id="a", cart_id="ca")
    await store.upsert("B", session_id="b", cart_id="cb")
    a = await store.get("A")
    b = await store.get("B")
    assert a["session_id"] == "a" and a["cart_id"] == "ca"
    assert b["session_id"] == "b" and b["cart_id"] == "cb"


@pytest.mark.asyncio
async def test_upsert_merges_does_not_overwrite_unrelated_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("STATE_DB_PATH", str(tmp_path / "merge.db"))
    store = ConversationStateStore()
    await store.upsert("C", session_id="s1", bpp_id="bpp1")
    # Second upsert with only cart_id should NOT clear session_id.
    await store.upsert("C", cart_id="cart1")
    row = await store.get("C")
    assert row["session_id"] == "s1"
    assert row["bpp_id"] == "bpp1"
    assert row["cart_id"] == "cart1"


@pytest.mark.asyncio
async def test_concurrent_upserts_dont_corrupt_state(tmp_path, monkeypatch):
    monkeypatch.setenv("STATE_DB_PATH", str(tmp_path / "conc.db"))
    store = ConversationStateStore()

    async def writer(i: int):
        await store.upsert(f"conv-{i}", session_id=f"s-{i}", cart_id=f"c-{i}")

    await asyncio.gather(*[writer(i) for i in range(50)])
    for i in range(50):
        row = await store.get(f"conv-{i}")
        assert row is not None
        assert row["session_id"] == f"s-{i}"
        assert row["cart_id"] == f"c-{i}"


@pytest.mark.asyncio
async def test_state_flows_search_to_cart(state_store):
    """End-to-end: search updates state; cart_add reads it; both rows linked."""
    payload = safiya_search_payload("sess-link")

    import httpx

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST" and req.url.path == "/api/v1/search":
            return httpx.Response(200, json={
                "session_id": "sess-link", "transaction_id": "tx-link",
                "status": "pending", "bpp_id": "safiyafood.jaringan-dagang.id",
            })
        if req.url.path == "/api/v1/search/sess-link/results":
            return httpx.Response(200, json=payload)
        if req.method == "POST" and req.url.path == "/api/v1/cart/select":
            # The MCP server must forward the session_id from state — assert it.
            body = req.read()
            assert b"sess-link" in body
            assert b"safiyafood.jaringan-dagang.id" in body
            return httpx.Response(200, json={
                "cart_id": "cart-link", "transaction_id": "tx-link", "status": "open",
            })
        if req.url.path == "/api/v1/cart/cart-link":
            return httpx.Response(200, json={
                "cart_id": "cart-link", "status": "open",
                "bpp_id": "safiyafood.jaringan-dagang.id", "bpp_uri": None,
                "provider_id": "safiya-prov-1",
                "transaction_id": "tx-link", "items": [], "quote": None,
                "quote_token": None, "billing": None, "shipping": None,
            })
        return httpx.Response(404)

    ctx = make_ctx(handler, state_store)
    await search_products(ctx, {"conversation_id": "C1", "query": "rendang"})
    await cart_add(ctx, {
        "conversation_id": "C1",
        "items": [{"item_id": "SKU-1", "qty": 1}],
    })
    row = await state_store.get("C1")
    assert row["session_id"] == "sess-link"
    assert row["cart_id"] == "cart-link"
    assert row["bpp_id"] == "safiyafood.jaringan-dagang.id"


def test_fallback_path_when_default_unwritable(monkeypatch, tmp_path):
    """If STATE_DB_PATH isn't supplied and /var/lib path isn't writable,
    the store falls back to /tmp without raising."""
    # Force a non-writable explicit path so resolver moves on.
    monkeypatch.delenv("STATE_DB_PATH", raising=False)
    # Simulate /var/lib unwritable by patching the default constant.
    import lib.conversation_state as mod
    monkeypatch.setattr(mod, "DEFAULT_DB_PATH", "/proc/jd-sell-mcp/state.db")
    fallback = str(tmp_path / "fallback.db")
    monkeypatch.setattr(mod, "FALLBACK_DB_PATH", fallback)
    store = ConversationStateStore()
    assert store.db_path == fallback
    assert os.path.exists(fallback)
