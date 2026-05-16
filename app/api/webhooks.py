"""External webhook endpoints (Biteship, Xendit, etc.)."""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from app.database import async_session_factory
from app.models.fulfillment import FulfillmentRecord, FulfillmentStatus
from app.models.order import Order

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# Map Biteship status codes -> our FulfillmentStatus enum
_BITESHIP_STATUS_MAP: dict[str, FulfillmentStatus] = {
    "confirmed": FulfillmentStatus.PENDING,
    "scheduled": FulfillmentStatus.PENDING,
    "allocated": FulfillmentStatus.PENDING,
    "picking_up": FulfillmentStatus.PENDING,
    "picked_up": FulfillmentStatus.PICKED_UP,
    "in_transit": FulfillmentStatus.IN_TRANSIT,
    "on_hold": FulfillmentStatus.IN_TRANSIT,
    "delivering": FulfillmentStatus.IN_TRANSIT,
    "out_for_delivery": FulfillmentStatus.IN_TRANSIT,
    "delivered": FulfillmentStatus.DELIVERED,
}


def _verify_biteship_signature(raw: bytes, sig: str) -> bool:
    """HMAC-SHA256 verify with BITESHIP_WEBHOOK_SECRET. If unset, accept (dev)."""
    secret = os.environ.get("BITESHIP_WEBHOOK_SECRET")
    if not secret:
        return True  # dev mode — accept anything
    computed = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, sig)


@router.post("/biteship")
async def biteship_webhook(request: Request) -> dict:
    """Receive Biteship status updates.

    Idempotent: dedupes on the event_id field. Updates FulfillmentRecord,
    then emits /on_status to the BAP.
    """
    raw = await request.body()
    sig = request.headers.get("X-Biteship-Signature", "")
    if not _verify_biteship_signature(raw, sig):
        raise HTTPException(401, "Bad Biteship signature")

    try:
        evt: dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(400, "Malformed JSON")

    event_id = evt.get("event_id") or evt.get("id") or ""
    bite_order_id = evt.get("order_id") or evt.get("courier", {}).get("order_id")
    status_code = evt.get("status") or evt.get("courier_status")
    awb = evt.get("courier_waybill_id") or evt.get("courier", {}).get("waybill_id")
    tracking_url = evt.get("tracking_url") or evt.get("courier", {}).get("tracking_url")

    if not bite_order_id and not awb:
        return {"ok": True, "note": "no order_id or awb — ignored"}

    new_status = _BITESHIP_STATUS_MAP.get(status_code or "")

    async with async_session_factory() as session:
        # Look up fulfillment by AWB (preferred) or fall back to a search by
        # courier ref stored in the FulfillmentRecord (TBD wiring at order create).
        fr = None
        if awb:
            fr = (
                await session.execute(
                    select(FulfillmentRecord).where(FulfillmentRecord.awb_number == awb)
                )
            ).scalar_one_or_none()

        if fr is None:
            logger.info("biteship webhook: no matching fulfillment for awb=%s order=%s", awb, bite_order_id)
            return {"ok": True, "note": "no matching fulfillment yet"}

        if new_status:
            fr.status = new_status
        if awb and not fr.awb_number:
            fr.awb_number = awb
        if tracking_url:
            fr.tracking_url = tracking_url
        await session.commit()
        order_id = fr.order_id

    # Fire-and-forget /on_status emit
    try:
        from app.beckn.status_push import emit_on_status_for_order
        import asyncio
        asyncio.create_task(emit_on_status_for_order(order_id))
    except Exception:
        logger.exception("failed to enqueue /on_status emit for %s", order_id)

    return {"ok": True, "event_id": event_id, "order_id": str(order_id)}
