"""Biteship shipping/logistics integration.

Uses httpx to call Biteship REST API.
Biteship API base: https://api.biteship.com/v1
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def _biteship_headers() -> dict[str, str]:
    """Build headers for Biteship API requests."""
    return {
        "Authorization": f"Bearer {settings.BITESHIP_API_KEY or ''}",
        "Content-Type": "application/json",
    }


async def get_rates(
    *,
    origin_postal_code: str,
    destination_postal_code: str,
    items: list[dict[str, Any]],
    couriers: str = "jne,jnt,sicepat,anteraja,tiki",
) -> list[dict[str, Any]]:
    """Get shipping rates from Biteship.

    POST https://api.biteship.com/v1/rates/couriers

    Args:
        origin_postal_code: Sender's postal code.
        destination_postal_code: Receiver's postal code.
        items: List of items with name, weight, quantity, value.
        couriers: Comma-separated courier codes.

    Returns:
        List of courier rate options from Biteship.
    """
    if not settings.BITESHIP_API_KEY:
        logger.warning("BITESHIP_API_KEY not set; returning mock rates")
        return [
            {
                "courier_code": "jne",
                "courier_service_code": "REG",
                "courier_service_name": "JNE Regular",
                "duration": "2-3 days",
                "price": 15000,
            },
            {
                "courier_code": "sicepat",
                "courier_service_code": "REG",
                "courier_service_name": "SiCepat Regular",
                "duration": "1-2 days",
                "price": 12000,
            },
        ]

    payload = {
        "origin_postal_code": int(origin_postal_code),
        "destination_postal_code": int(destination_postal_code),
        "couriers": couriers,
        "items": items,
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{settings.BITESHIP_API_BASE}/rates/couriers",
            headers=_biteship_headers(),
            json=payload,
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()

    pricing = data.get("pricing", [])
    rates: list[dict[str, Any]] = []
    for rate in pricing:
        rates.append(
            {
                "courier_code": rate.get("courier_code"),
                "courier_service_code": rate.get("courier_service_code"),
                "courier_service_name": rate.get("courier_service_name"),
                "duration": rate.get("duration"),
                "price": rate.get("price"),
            }
        )
    return rates


async def create_shipment(
    *,
    origin: dict[str, Any],
    destination: dict[str, Any],
    courier_code: str,
    courier_service_code: str,
    items: list[dict[str, Any]],
    order_reference: str,
) -> dict[str, Any]:
    """Create a shipment order with Biteship.

    POST https://api.biteship.com/v1/orders

    Returns:
        Dict with id, courier_waybill_id, courier_tracking_id, tracking info.
    """
    if not settings.BITESHIP_API_KEY:
        logger.warning("BITESHIP_API_KEY not set; returning mock shipment")
        return {
            "id": f"dev-ship-{uuid.uuid4()}",
            "courier_waybill_id": f"AWB-DEV-{uuid.uuid4().hex[:8].upper()}",
            "courier_tracking_id": f"TRK-DEV-{uuid.uuid4().hex[:8].upper()}",
            "status": "confirmed",
        }

    payload = {
        "shipper_contact_name": origin.get("contact_name"),
        "shipper_contact_phone": origin.get("contact_phone"),
        "shipper_contact_email": origin.get("contact_email"),
        "shipper_organization": origin.get("organization"),
        "origin_contact_name": origin.get("contact_name"),
        "origin_contact_phone": origin.get("contact_phone"),
        "origin_address": origin.get("address"),
        "origin_postal_code": int(origin.get("postal_code", 0)),
        "destination_contact_name": destination.get("contact_name"),
        "destination_contact_phone": destination.get("contact_phone"),
        "destination_address": destination.get("address"),
        "destination_postal_code": int(destination.get("postal_code", 0)),
        "courier_company": courier_code,
        "courier_type": courier_service_code,
        "delivery_type": "now",
        "order_note": f"Jaringan Dagang - {order_reference}",
        "items": items,
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{settings.BITESHIP_API_BASE}/orders",
            headers=_biteship_headers(),
            json=payload,
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()

    return {
        "id": data.get("id"),
        "courier_waybill_id": data.get("courier", {}).get("waybill_id"),
        "courier_tracking_id": data.get("courier", {}).get("tracking_id"),
        "status": data.get("status"),
    }


async def track_shipment(biteship_order_id: str) -> dict[str, Any]:
    """Get tracking information for a Biteship order.

    GET https://api.biteship.com/v1/trackings/{id}
    """
    if not settings.BITESHIP_API_KEY:
        logger.warning("BITESHIP_API_KEY not set; returning mock tracking")
        return {
            "status": "in_transit",
            "courier_tracking_id": "TRK-MOCK",
            "history": [],
        }

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{settings.BITESHIP_API_BASE}/trackings/{biteship_order_id}",
            headers=_biteship_headers(),
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()
