"""Xendit payment gateway integration.

Uses httpx to call Xendit REST API directly (not the SDK).
Xendit API base: https://api.xendit.co
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.payment import PaymentRecord, PaymentStatus

logger = logging.getLogger(__name__)


def _xendit_headers() -> dict[str, str]:
    """Build headers for Xendit API requests using Basic auth."""
    import base64

    secret = settings.XENDIT_SECRET_KEY or ""
    token = base64.b64encode(f"{secret}:".encode()).decode()
    return {
        "Authorization": f"Basic {token}",
        "Content-Type": "application/json",
    }


async def create_invoice(
    db: AsyncSession,
    order_id: uuid.UUID,
    amount: Decimal,
    *,
    payer_email: str | None = None,
    description: str = "Jaringan Dagang Order",
    currency: str = "IDR",
) -> PaymentRecord:
    """Create a Xendit invoice and persist a PaymentRecord.

    POST https://api.xendit.co/v2/invoices
    """
    external_id = f"jd-{order_id}"

    payload: dict[str, Any] = {
        "external_id": external_id,
        "amount": float(amount),
        "currency": currency,
        "description": description,
    }
    if payer_email:
        payload["payer_email"] = payer_email

    xendit_invoice_id: str | None = None
    invoice_url: str | None = None

    if settings.XENDIT_SECRET_KEY:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{settings.XENDIT_API_BASE}/v2/invoices",
                headers=_xendit_headers(),
                json=payload,
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
            xendit_invoice_id = data.get("id")
            invoice_url = data.get("invoice_url")
            logger.info(
                "Xendit invoice created: %s -> %s", xendit_invoice_id, invoice_url
            )
    else:
        # Sandbox / dev mode -- no real Xendit call
        logger.warning("XENDIT_SECRET_KEY not set; skipping real invoice creation")
        xendit_invoice_id = f"dev-{uuid.uuid4()}"

    payment = PaymentRecord(
        order_id=order_id,
        xendit_invoice_id=xendit_invoice_id,
        amount=amount,
        status=PaymentStatus.PENDING,
    )
    db.add(payment)
    await db.flush()
    return payment


async def handle_webhook(
    db: AsyncSession,
    payload: dict[str, Any],
) -> PaymentRecord | None:
    """Process a Xendit invoice/payment callback.

    Updates the PaymentRecord based on Xendit webhook data.
    """
    from sqlalchemy import select

    xendit_invoice_id = payload.get("id")
    status_str = payload.get("status", "").upper()

    stmt = select(PaymentRecord).where(
        PaymentRecord.xendit_invoice_id == xendit_invoice_id
    )
    result = await db.execute(stmt)
    payment = result.scalar_one_or_none()

    if payment is None:
        logger.warning(
            "Webhook for unknown Xendit invoice: %s", xendit_invoice_id
        )
        return None

    status_map = {
        "PAID": PaymentStatus.PAID,
        "SETTLED": PaymentStatus.PAID,
        "EXPIRED": PaymentStatus.EXPIRED,
        "FAILED": PaymentStatus.FAILED,
    }

    new_status = status_map.get(status_str)
    if new_status:
        payment.status = new_status

    if new_status == PaymentStatus.PAID:
        payment.paid_at = datetime.utcnow()

    payment.xendit_payment_id = payload.get("payment_id")
    payment.method = payload.get("payment_method")
    payment.channel = payload.get("payment_channel")
    payment.callback_data = payload

    await db.flush()
    logger.info(
        "Payment %s updated to %s via webhook", payment.id, payment.status
    )
    return payment
