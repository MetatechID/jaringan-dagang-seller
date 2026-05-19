"""Emit Beckn /on_status to the BAP when an order's fulfillment state changes.

Called by the Biteship webhook handler. Also called from order-status changes
elsewhere if needed.
"""

from __future__ import annotations

import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.beckn.callback_sender import load_bpp_signing_key_b64, send_callback
from app.config import settings
from app.database import async_session_factory
from app.models.fulfillment import FulfillmentRecord
from app.models.order import Order
from app.models.store import Store

# Make beckn-protocol importable
_proto_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "packages", "beckn-protocol")
)
if _proto_path not in sys.path:
    sys.path.insert(0, _proto_path)

from python.domain_resolver import resolve_ondc_domain  # noqa: E402

logger = logging.getLogger(__name__)


def _ctx(
    *,
    bap_id: str,
    bap_uri: str,
    bpp_id: str,
    bpp_uri: str,
    txn_id: str,
    store_subscriber_id: str | None = None,
) -> dict[str, Any]:
    # Per-store ONDC domain code (Safiya -> ONDC:RET11); unknown/missing
    # store falls back to the store-level ONDC:RET default. The Beckn
    # transport base (settings.BECKN_DOMAIN) is unchanged by this layer.
    return {
        "domain": resolve_ondc_domain(store_subscriber_id).domain_code,
        "country": settings.BECKN_COUNTRY_CODE,
        "city": settings.BECKN_CITY_CODE,
        "action": "on_status",
        "core_version": settings.BECKN_CORE_VERSION,
        "bap_id": bap_id,
        "bap_uri": bap_uri,
        "bpp_id": bpp_id,
        "bpp_uri": bpp_uri,
        "transaction_id": txn_id,
        "message_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def emit_on_status_for_order(order_id) -> bool:
    """Build and POST a Beckn /on_status callback for one order."""
    async with async_session_factory() as session:
        result = await session.execute(
            select(Order)
            .where(Order.id == order_id)
            .options(selectinload(Order.fulfillment))
        )
        order: Order | None = result.scalar_one_or_none()
        if order is None:
            logger.warning("emit_on_status: order %s not found", order_id)
            return False

        store = await session.get(Store, order.store_id)
        if store is None:
            return False

        f: FulfillmentRecord | None = order.fulfillment
        f_state_code = f.status.value if f and f.status else "pending"
        f_payload: dict[str, Any] = {
            "id": str(f.id) if f else "fulfillment-delivery",
            "type": f.type if f else "Delivery",
            "state": {"descriptor": {"code": f_state_code}},
            "tracking": True,
        }
        if f and f.awb_number:
            f_payload["tracking_id"] = f.awb_number
        if f and f.tracking_url:
            f_payload["tracking_url"] = f.tracking_url

    bap_id = order.bap_id or settings.BELI_AMAN_BAP_ID
    bap_uri = settings.BELI_AMAN_BAP_URL
    bpp_id = settings.BPP_SUBSCRIBER_ID
    bpp_uri = settings.BPP_SUBSCRIBER_URL
    store_subscriber_id = store.subscriber_id

    body = {
        "context": _ctx(
            bap_id=bap_id, bap_uri=bap_uri,
            bpp_id=bpp_id, bpp_uri=bpp_uri,
            txn_id=str(order.id),
            store_subscriber_id=store_subscriber_id,
        ),
        "message": {
            "order": {
                "id": order.beckn_order_id or str(order.id),
                "state": order.status.value if order.status else "CREATED",
                "fulfillments": [f_payload],
            }
        },
    }

    try:
        ok = await send_callback(
            bap_uri=bap_uri,
            action="on_status",
            response_body=body,
            signing_private_key_b64=load_bpp_signing_key_b64(),
        )
        logger.info("on_status -> %s : %s", bap_uri, "ok" if ok else "fail")
        return ok
    except Exception:
        logger.exception("emit_on_status failed for %s", order_id)
        return False
