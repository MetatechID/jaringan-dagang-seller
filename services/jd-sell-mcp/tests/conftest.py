"""Shared pytest fixtures.

The MCP server's only external dependency is the BAP. We stub it with
``httpx.MockTransport`` (in-process; no socket churn) so the tools think
they're calling the real BAP but a small Python handler decides the
response. This is fast, deterministic, and works without ``respx``.

Each test gets its own SQLite tempfile (``state_store`` fixture) so state
doesn't leak across tests.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Callable

import httpx
import pytest

# Make the service root importable as a top-level package set.
_HERE = os.path.dirname(__file__)
_SVC_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _SVC_ROOT not in sys.path:
    sys.path.insert(0, _SVC_ROOT)

# Speed up search poll under tests — production cadence (1.5s × 8) would make
# the suite painfully slow. The interval is read from a module-level constant
# so we just monkeypatch it once per session.
import tools.search as _search_mod  # noqa: E402

_search_mod.SEARCH_POLL_INTERVAL_SEC = 0.01
_search_mod.SEARCH_POLL_MAX_SECONDS = 0.1

import tools.cart as _cart_mod  # noqa: E402

_cart_mod.CART_QUOTE_POLL_DELAY_SEC = 0.0

from lib.bap_client import BAPClient  # noqa: E402
from lib.conversation_state import ConversationStateStore  # noqa: E402
from tools import ToolContext  # noqa: E402


BAPHandler = Callable[[httpx.Request], httpx.Response]


def make_bap_client(handler: BAPHandler, token: str = "test-token") -> BAPClient:
    transport = httpx.MockTransport(handler)
    httpx_client = httpx.AsyncClient(transport=transport, base_url="http://bap.test")
    client = BAPClient(
        base_url="http://bap.test",
        token=token,
        timeout_sec=5.0,
        client=httpx_client,
    )
    return client


@pytest.fixture
def state_store(tmp_path, monkeypatch) -> ConversationStateStore:
    monkeypatch.setenv("STATE_DB_PATH", str(tmp_path / "state.db"))
    return ConversationStateStore()


def make_ctx(handler: BAPHandler, state: ConversationStateStore) -> ToolContext:
    return ToolContext(
        bap=make_bap_client(handler),
        state=state,
        catalog_cache_ttl_sec=300,
    )


# ---------- Convenience stub BAPs ----------


def static_bap(routes: dict[tuple[str, str], dict[str, Any]]) -> BAPHandler:
    """Return a handler that maps (method, path) → JSON body (200 OK).

    Routes whose paths end with ``/*`` match by prefix.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        key = (request.method.upper(), request.url.path)
        if key in routes:
            return httpx.Response(200, json=routes[key])
        # Path-prefix fallback.
        for (m, p), body in routes.items():
            if p.endswith("/*") and key[0] == m and key[1].startswith(p[:-2]):
                return httpx.Response(200, json=body)
        return httpx.Response(404, json={"detail": f"no stub for {key}"})

    return handler


def safiya_search_payload(session_id: str) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "status": "results",
        "results": [
            {
                "bpp_id": "safiyafood.jaringan-dagang.id",
                "bpp_uri": "https://safiyafood.example.id",
                "provider_id": "safiya-prov-1",
                "store_slug": "safiya",
                "store_name": "Safiya Food",
                "products": [
                    {
                        "product_id": "PROD-1",
                        "sku": "RENDANG-200",
                        "name": "Rendang Sapi 200g",
                        "description": "Rendang sapi premium siap saji",
                        "status": "active",
                        "images": [],
                        "skus": [
                            {
                                "sku_id": "SKU-1",
                                "sku_code": "RDG-200",
                                "variant_name": "Pedas",
                                "variant_value": "Sedang",
                                "price_idr": 65000,
                                "original_price_idr": 75000,
                                "stock": 50,
                                "images": [],
                            }
                        ],
                    },
                    {
                        "product_id": "PROD-2",
                        "sku": "GULAI-200",
                        "name": "Gulai Ayam 200g",
                        "description": None,
                        "status": "active",
                        "images": [],
                        "skus": [
                            {
                                "sku_id": "SKU-2",
                                "sku_code": "GLA-200",
                                "variant_name": None,
                                "variant_value": None,
                                "price_idr": 55000,
                                "original_price_idr": None,
                                "stock": 30,
                                "images": [],
                            }
                        ],
                    },
                ],
            }
        ],
    }
