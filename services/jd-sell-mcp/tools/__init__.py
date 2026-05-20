"""MCP tool registry + dispatch table.

The six tools live in sibling modules; this file is the single place to
declare their name → (callable, JSON-schema) wiring. ``main.py`` and
``mcp_protocol.py`` import only ``TOOLS`` from here so they stay decoupled
from individual tool internals.

Each tool callable has the signature::

    async def tool(ctx: ToolContext, arguments: dict[str, Any]) -> ToolResult

ToolResult.content is the MCP ``content`` array (list of {type, text}).
ToolResult.is_error mirrors MCP's optional ``isError`` flag.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from lib.bap_client import BAPClient
from lib.conversation_state import ConversationStateStore

from .cart import cart_add, cart_view
from .checkout import payment_status, start_checkout
from .search import get_product, search_products


@dataclass
class ToolContext:
    """Per-request handles the tools need. Built once in main.py lifespan."""

    bap: BAPClient
    state: ConversationStateStore
    # ``search_cache`` is a process-local dict — survives across calls inside
    # one MCP server process but not across restarts. The bot calls
    # ``get_product`` only after a recent ``search_products``, so this is fine.
    search_cache: dict[str, dict[str, Any]] = field(default_factory=dict)
    catalog_cache_ttl_sec: int = 300


@dataclass
class ToolResult:
    content: list[dict[str, Any]]
    is_error: bool = False


ToolFn = Callable[[ToolContext, dict[str, Any]], Awaitable[ToolResult]]


# ----- JSON schemas (kept inline; would be overkill to split into files) -----

_CONVERSATION_ID_FIELD = {
    "type": "string",
    "description": "Stable UUID-shaped identifier the bot generates per chat.",
    "minLength": 1,
}


_SCHEMAS: dict[str, dict[str, Any]] = {
    "search_products": {
        "type": "object",
        "properties": {
            "conversation_id": _CONVERSATION_ID_FIELD,
            "query": {"type": "string", "minLength": 1, "maxLength": 500},
            "category": {"type": "string"},
            "city": {
                "type": "string",
                "description": "Beckn city code, e.g. 'std:021' (Jakarta).",
            },
        },
        "required": ["conversation_id", "query"],
        "additionalProperties": False,
    },
    "get_product": {
        "type": "object",
        "properties": {
            "conversation_id": _CONVERSATION_ID_FIELD,
            "item_id": {"type": "string", "minLength": 1},
        },
        "required": ["conversation_id", "item_id"],
        "additionalProperties": False,
    },
    "cart_add": {
        "type": "object",
        "properties": {
            "conversation_id": _CONVERSATION_ID_FIELD,
            "items": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "item_id": {"type": "string", "minLength": 1},
                        "qty": {"type": "integer", "minimum": 1},
                    },
                    "required": ["item_id", "qty"],
                },
            },
        },
        "required": ["conversation_id", "items"],
        "additionalProperties": False,
    },
    "cart_view": {
        "type": "object",
        "properties": {"conversation_id": _CONVERSATION_ID_FIELD},
        "required": ["conversation_id"],
        "additionalProperties": False,
    },
    "start_checkout": {
        "type": "object",
        "properties": {
            "conversation_id": _CONVERSATION_ID_FIELD,
            "billing": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "email": {"type": "string"},
                    "phone": {"type": "string"},
                },
                "required": ["name", "email", "phone"],
            },
            "shipping": {
                "type": "object",
                "properties": {
                    "address": {"type": "string"},
                    "city": {"type": "string"},
                    "postal_code": {"type": "string"},
                    "recipient_name": {"type": "string"},
                    "recipient_phone": {"type": "string"},
                },
                "required": [
                    "address", "city", "postal_code",
                    "recipient_name", "recipient_phone",
                ],
            },
        },
        "required": ["conversation_id", "billing", "shipping"],
        "additionalProperties": False,
    },
    "payment_status": {
        "type": "object",
        "properties": {"conversation_id": _CONVERSATION_ID_FIELD},
        "required": ["conversation_id"],
        "additionalProperties": False,
    },
}


_DESCRIPTIONS: dict[str, str] = {
    "search_products": (
        "Cari produk Safiya berdasarkan kata kunci. Server akan polling BAP "
        "selama ~12 detik dan mengembalikan 5 produk teratas plus detail JSON."
    ),
    "get_product": (
        "Tampilkan detail satu produk dari hasil pencarian sebelumnya pada "
        "percakapan ini. Tidak memanggil BAP — pakai cache pencarian."
    ),
    "cart_add": (
        "Tambahkan satu atau lebih item (item_id + qty) ke keranjang. "
        "Otomatis mengaitkan sesi pencarian aktif dan mengembalikan kuotasi."
    ),
    "cart_view": (
        "Tampilkan isi keranjang aktif dan kuotasi terbaru untuk percakapan ini."
    ),
    "start_checkout": (
        "Mulai checkout: kirim alamat tagihan + pengiriman, dapatkan QR "
        "pembayaran dan link invoice. Status pembayaran dicek terpisah lewat "
        "payment_status."
    ),
    "payment_status": (
        "Cek status pembayaran untuk keranjang aktif (pending/paid/expired/"
        "failed). Bot akan memanggilnya berulang sampai status final."
    ),
}


_FUNCTIONS: dict[str, ToolFn] = {
    "search_products": search_products,
    "get_product": get_product,
    "cart_add": cart_add,
    "cart_view": cart_view,
    "start_checkout": start_checkout,
    "payment_status": payment_status,
}


def tool_descriptors() -> list[dict[str, Any]]:
    """Shape required by MCP ``tools/list``."""
    return [
        {
            "name": name,
            "description": _DESCRIPTIONS[name],
            "inputSchema": _SCHEMAS[name],
        }
        for name in _FUNCTIONS
    ]


def dispatch(name: str) -> ToolFn | None:
    return _FUNCTIONS.get(name)


TOOLS = sorted(_FUNCTIONS.keys())
