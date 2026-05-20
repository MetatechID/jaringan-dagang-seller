"""``start_checkout`` + ``payment_status`` MCP tools."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from lib.bap_client import BAPHTTPError, BAPTransportError
from lib.markdown_format import (
    render_error,
    render_tool_response,
    summarize_checkout,
    summarize_payment_state,
)

from .search import _err, _map_http_error, _map_transport_error, _ok

if TYPE_CHECKING:  # pragma: no cover
    from . import ToolContext, ToolResult

logger = logging.getLogger(__name__)


def _to_bap_billing(billing: dict[str, Any]) -> dict[str, Any]:
    """Map the bot's billing shape to the BAP's AddressIn shape."""
    return {
        "name": billing.get("name"),
        "email": billing.get("email"),
        "phone": billing.get("phone"),
    }


def _to_bap_shipping(shipping: dict[str, Any]) -> dict[str, Any]:
    """Map the bot's shipping shape to the BAP's AddressIn shape.

    The BAP's AddressIn uses ``line1`` / ``name`` / ``phone``; we map:
      * shipping.address       → line1
      * shipping.recipient_name → name
      * shipping.recipient_phone → phone
    Other fields pass through 1:1.
    """
    return {
        "name": shipping.get("recipient_name"),
        "phone": shipping.get("recipient_phone"),
        "line1": shipping.get("address"),
        "city": shipping.get("city"),
        "postal_code": shipping.get("postal_code"),
    }


async def start_checkout(
    ctx: "ToolContext", arguments: dict[str, Any],
) -> "ToolResult":
    conversation_id = arguments["conversation_id"]
    billing = arguments["billing"]
    shipping = arguments["shipping"]

    state = await ctx.state.get(conversation_id)
    if state is None or not state.get("cart_id"):
        return _err(render_error(
            "Belum ada keranjang aktif. Tambah item ke keranjang dulu, "
            "lalu mulai checkout.",
        ))
    cart_id = state["cart_id"]

    bap_billing = _to_bap_billing(billing)
    bap_shipping = _to_bap_shipping(shipping)

    try:
        init_resp = await ctx.bap.cart_init(
            cart_id, billing=bap_billing, shipping=bap_shipping,
        )
    except BAPHTTPError as exc:
        return _map_http_error(exc)
    except BAPTransportError as exc:
        return _map_transport_error(exc)

    await ctx.state.upsert(
        conversation_id,
        billing=billing,
        shipping=shipping,
    )

    quote_token = init_resp.get("quote_token")

    try:
        confirmed = await ctx.bap.confirm(cart_id, quote_token=quote_token)
    except BAPHTTPError as exc:
        return _map_http_error(exc)
    except BAPTransportError as exc:
        return _map_transport_error(exc)

    payment = confirmed.get("payment") or {}
    order_id = confirmed.get("order_id")
    summary = summarize_checkout(payment, order_id)
    return _ok(render_tool_response(summary, confirmed))


async def payment_status(
    ctx: "ToolContext", arguments: dict[str, Any],
) -> "ToolResult":
    conversation_id = arguments["conversation_id"]
    state = await ctx.state.get(conversation_id)
    if state is None or not state.get("cart_id"):
        return _err(render_error(
            "Belum ada pesanan untuk dicek. Mulai checkout dulu.",
        ))

    try:
        s = await ctx.bap.checkout_status(state["cart_id"])
    except BAPHTTPError as exc:
        return _map_http_error(exc)
    except BAPTransportError as exc:
        return _map_transport_error(exc)

    summary = summarize_payment_state(
        s.get("payment_state") or "unknown",
        s.get("order_id"),
    )
    return _ok(render_tool_response(summary, s))
