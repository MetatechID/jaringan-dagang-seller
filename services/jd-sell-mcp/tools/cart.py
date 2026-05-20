"""``cart_add`` + ``cart_view`` MCP tools."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from lib.bap_client import BAPHTTPError, BAPTransportError
from lib.markdown_format import (
    render_error,
    render_tool_response,
    summarize_cart,
)

from .search import _err, _map_http_error, _map_transport_error, _ok

if TYPE_CHECKING:  # pragma: no cover
    from . import ToolContext, ToolResult

logger = logging.getLogger(__name__)


# One short re-poll after /select to give /on_select a chance to wire a quote.
CART_QUOTE_POLL_DELAY_SEC = 1.0


async def cart_add(
    ctx: "ToolContext", arguments: dict[str, Any],
) -> "ToolResult":
    conversation_id = arguments["conversation_id"]
    items = arguments["items"]

    state = await ctx.state.get(conversation_id)
    if state is None or not state.get("bpp_id"):
        return _err(render_error(
            "Belum ada konteks pesanan. Mulai dari cari produk dulu?",
        ))

    # If the cached search has a known provider_id for this BPP, surface it.
    provider_id: str | None = None
    cache = ctx.search_cache.get(conversation_id)
    if cache:
        for store in cache.get("raw") or []:
            if store.get("bpp_id") == state.get("bpp_id"):
                provider_id = store.get("provider_id")
                break

    try:
        selected = await ctx.bap.cart_select(
            session_id=state.get("session_id"),
            bpp_id=state["bpp_id"],
            bpp_uri=state.get("bpp_uri"),
            provider_id=provider_id,
            items=[{"item_id": it["item_id"], "qty": int(it["qty"])} for it in items],
        )
    except BAPHTTPError as exc:
        return _map_http_error(exc)
    except BAPTransportError as exc:
        return _map_transport_error(exc)

    cart_id = selected["cart_id"]
    await ctx.state.upsert(
        conversation_id,
        cart_id=cart_id,
        transaction_id=selected.get("transaction_id"),
    )

    # Brief grace period before pulling the quote.
    await asyncio.sleep(CART_QUOTE_POLL_DELAY_SEC)
    try:
        cart = await ctx.bap.get_cart(cart_id)
    except BAPHTTPError as exc:
        return _map_http_error(exc)
    except BAPTransportError as exc:
        return _map_transport_error(exc)

    summary = summarize_cart(cart)
    return _ok(render_tool_response(summary, cart))


async def cart_view(
    ctx: "ToolContext", arguments: dict[str, Any],
) -> "ToolResult":
    conversation_id = arguments["conversation_id"]
    state = await ctx.state.get(conversation_id)
    if state is None or not state.get("cart_id"):
        return _err(render_error(
            "Belum ada keranjang aktif untuk percakapan ini. Tambah item "
            "terlebih dahulu dengan cart_add.",
        ))

    try:
        cart = await ctx.bap.get_cart(state["cart_id"])
    except BAPHTTPError as exc:
        return _map_http_error(exc)
    except BAPTransportError as exc:
        return _map_transport_error(exc)

    return _ok(render_tool_response(summarize_cart(cart), cart))
