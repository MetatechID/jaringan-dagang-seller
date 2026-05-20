"""``search_products`` + ``get_product`` MCP tools."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from lib.bap_client import BAPHTTPError, BAPTransportError
from lib.markdown_format import (
    render_error,
    render_tool_response,
    summarize_product,
    summarize_search,
)

if TYPE_CHECKING:  # pragma: no cover
    from . import ToolContext, ToolResult

logger = logging.getLogger(__name__)


# Poll cadence: BAP returns status=pending until on_search callbacks land.
# Real-world callback latency from a healthy BPP is sub-second; we give it
# ~12 seconds total before returning whatever we have (possibly empty).
SEARCH_POLL_INTERVAL_SEC = 1.5
SEARCH_POLL_MAX_SECONDS = 12.0


def _ok(content_text: str) -> "ToolResult":
    from . import ToolResult  # local to avoid circular import
    return ToolResult(content=[{"type": "text", "text": content_text}])


def _err(content_text: str) -> "ToolResult":
    from . import ToolResult
    return ToolResult(
        content=[{"type": "text", "text": content_text}], is_error=True
    )


def _map_http_error(exc: BAPHTTPError) -> "ToolResult":
    if exc.status_code == 401:
        return _err(render_error(
            "Saya tidak punya akses ke katalog Safiya. Mohon coba lagi atau "
            "hubungi admin.",
            {"bap_status": 401, "bap_body": exc.body},
        ))
    if exc.status_code == 404:
        return _err(render_error(
            "Data yang dicari tidak ditemukan di BAP.",
            {"bap_status": 404, "bap_body": exc.body},
        ))
    if exc.status_code == 409:
        return _err(render_error(
            "Permintaan ini tidak bisa dijalankan pada status saat ini.",
            {"bap_status": 409, "bap_body": exc.body},
        ))
    if exc.status_code == 410:
        return _err(render_error(
            "Sesi atau keranjang sudah kedaluwarsa. Mulai pencarian baru.",
            {"bap_status": 410, "bap_body": exc.body},
        ))
    return _err(render_error(
        "Sistem sedang sibuk, mohon coba lagi sebentar.",
        {"bap_status": exc.status_code, "bap_body": exc.body},
    ))


def _map_transport_error(exc: BAPTransportError) -> "ToolResult":
    logger.warning("BAP transport error: %s", exc)
    return _err(render_error(
        "Sistem sedang sibuk, mohon coba lagi sebentar.",
        {"error": "transport_error"},
    ))


def _flatten_products(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Build ``product_id → {product, store_block}`` index for get_product."""
    index: dict[str, dict[str, Any]] = {}
    for store in results:
        for prod in store.get("products") or []:
            pid = prod.get("product_id")
            if not pid:
                continue
            index[str(pid)] = {
                "product": prod,
                "store": {
                    "bpp_id": store.get("bpp_id"),
                    "bpp_uri": store.get("bpp_uri"),
                    "provider_id": store.get("provider_id"),
                    "store_name": store.get("store_name"),
                },
            }
            # Also index by every SKU id within this product so a customer
            # asking for "@SKU-123" hits the same record without an extra
            # roundtrip.
            for sku in prod.get("skus") or []:
                sid = sku.get("sku_id")
                if sid:
                    index[str(sid)] = {
                        "product": prod,
                        "sku": sku,
                        "store": index[str(pid)]["store"],
                    }
    return index


async def search_products(
    ctx: "ToolContext", arguments: dict[str, Any],
) -> "ToolResult":
    conversation_id = arguments["conversation_id"]
    query = arguments["query"]
    category = arguments.get("category")
    city = arguments.get("city")

    try:
        created = await ctx.bap.search(
            query=query, category=category, city=city,
        )
    except BAPHTTPError as exc:
        return _map_http_error(exc)
    except BAPTransportError as exc:
        return _map_transport_error(exc)

    session_id = created["session_id"]
    bpp_id = created.get("bpp_id")

    await ctx.state.upsert(
        conversation_id,
        session_id=session_id,
        bpp_id=bpp_id,
        transaction_id=created.get("transaction_id"),
    )

    # Poll for results.
    results_payload: dict[str, Any] = {"results": [], "status": "pending"}
    deadline = time.monotonic() + SEARCH_POLL_MAX_SECONDS
    while True:
        try:
            results_payload = await ctx.bap.get_search_results(session_id)
        except BAPHTTPError as exc:
            return _map_http_error(exc)
        except BAPTransportError as exc:
            return _map_transport_error(exc)

        if results_payload.get("results"):
            break
        if results_payload.get("status") in ("expired", "results"):
            break
        if time.monotonic() >= deadline:
            break
        await asyncio.sleep(SEARCH_POLL_INTERVAL_SEC)

    raw_results = results_payload.get("results") or []
    index = _flatten_products(raw_results)
    # Cache for ``get_product`` lookups. Single key per conversation; rewritten
    # on each new search (LLM only refers back to the latest one).
    ctx.search_cache[conversation_id] = {
        "expires_at": time.monotonic() + ctx.catalog_cache_ttl_sec,
        "query": query,
        "index": index,
        "raw": raw_results,
    }

    summary = summarize_search(raw_results)
    data = {
        "session_id": session_id,
        "bpp_id": bpp_id,
        "status": results_payload.get("status"),
        "result_count": sum(
            len(s.get("products") or []) for s in raw_results
        ),
        "results": raw_results,
    }
    return _ok(render_tool_response(summary, data))


async def get_product(
    ctx: "ToolContext", arguments: dict[str, Any],
) -> "ToolResult":
    conversation_id = arguments["conversation_id"]
    item_id = arguments["item_id"]

    cache = ctx.search_cache.get(conversation_id)
    if not cache:
        return _err(render_error(
            "Belum ada konteks pesanan. Mulai dari cari produk dulu?",
        ))
    if cache["expires_at"] < time.monotonic():
        ctx.search_cache.pop(conversation_id, None)
        return _err(render_error(
            "Cache pencarian sudah kedaluwarsa. Mohon lakukan pencarian ulang.",
        ))

    entry = cache["index"].get(str(item_id))
    if entry is None:
        return _err(render_error(
            f"Produk dengan id `{item_id}` tidak ditemukan di hasil pencarian "
            "terakhir.",
            {"item_id": item_id, "known_ids": sorted(cache["index"].keys())[:20]},
        ))

    product = entry["product"]
    summary = summarize_product(product)
    return _ok(render_tool_response(
        summary,
        {
            "product": product,
            "store": entry.get("store"),
            "matched_sku": entry.get("sku"),
        },
    ))
