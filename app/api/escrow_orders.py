"""Internal endpoint called by the Beli Aman BAP when escrow is held.

The BAP POSTs the order snapshot here so it materializes in the seller's
dashboard with full Beli Aman framing (badge + escrow status panel + verified
buyer card). Auth is a shared secret in the X-Internal-Token header.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.order import EscrowStatus, Order, OrderStatus
from app.models.store import Store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal", tags=["internal"])


class EscrowOrderBuyer(BaseModel):
    id: str
    email: str
    display_name: str | None = None
    photo_url: str | None = None


class EscrowOrderItem(BaseModel):
    sku: str
    name: str
    qty: int
    unit_price_idr: int
    image: str | None = None


class EscrowOrderIn(BaseModel):
    order_id: str  # the BAP's internal order id (used as beckn_order_id here)
    bap_id: str
    bpp_id: str | None = None
    buyer: EscrowOrderBuyer
    items: list[EscrowOrderItem]
    subtotal_idr: int
    shipping_idr: int = 0
    total_idr: int
    shipping_address: dict | None = None
    escrow_status: str = "held"


def require_internal_token(x_internal_token: str | None = Header(None)) -> None:
    expected = settings.BELI_AMAN_INTERNAL_TOKEN
    if not x_internal_token or x_internal_token != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing X-Internal-Token header",
        )


# Demo store id mirrors the seller-dashboard convention. In real onboarding,
# we'd resolve the store by `bpp_id` (e.g. bpp.antarestar.local → Store row).
DEMO_STORE_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


@router.post(
    "/escrow-orders",
    dependencies=[Depends(require_internal_token)],
    status_code=201,
)
async def create_escrow_order(
    body: EscrowOrderIn, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Materialize a Beli Aman order in the seller dashboard."""
    try:
        return await _create_escrow_order_impl(body, db)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("escrow_orders POST failed")
        raise HTTPException(500, f"escrow_orders error: {type(e).__name__}: {e}")


async def _create_escrow_order_impl(body: EscrowOrderIn, db: AsyncSession) -> dict[str, Any]:
    # Idempotency: skip if we've already seen this beckn_order_id.
    from sqlalchemy import select

    existing_q = await db.execute(
        select(Order).where(Order.beckn_order_id == body.order_id)
    )
    existing = existing_q.scalar_one_or_none()
    if existing:
        # Update escrow status (e.g. BAP re-posts after RELEASE).
        try:
            existing.escrow_status = EscrowStatus(body.escrow_status)
        except ValueError:
            pass
        existing.escrow_amount_idr = body.total_idr
        await db.commit()
        return {"id": str(existing.id), "status": "updated"}

    # Resolve target store by bpp_id (BAP knows which BPP it called).
    # Fall back to DEMO_STORE_ID for dev / backwards compat.
    store_id = DEMO_STORE_ID
    if body.bpp_id:
        store_q = await db.execute(select(Store).where(Store.subscriber_id == body.bpp_id))
        store_row = store_q.scalar_one_or_none()
        if store_row:
            store_id = store_row.id
        else:
            logger.warning(
                "Beli Aman order for unknown bpp_id=%s; falling back to demo store",
                body.bpp_id,
            )

    # New order
    try:
        escrow_status = EscrowStatus(body.escrow_status)
    except ValueError:
        escrow_status = EscrowStatus.HELD

    order = Order(
        store_id=store_id,
        beckn_order_id=body.order_id,
        buyer_name=body.buyer.display_name or body.buyer.email,
        buyer_email=body.buyer.email,
        buyer_photo_url=body.buyer.photo_url,
        billing_address=body.shipping_address,
        shipping_address=body.shipping_address,
        status=OrderStatus.ACCEPTED,  # auto-accepted because escrow is held
        total=Decimal(str(body.total_idr)),
        currency="IDR",
        items={
            "lines": [it.model_dump() for it in body.items],
            "shipping_idr": body.shipping_idr,
            "subtotal_idr": body.subtotal_idr,
        },
        bap_id=body.bap_id,
        escrow_status=escrow_status,
        escrow_amount_idr=body.total_idr,
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)

    logger.info(
        "Created Beli Aman order id=%s beckn=%s buyer=%s",
        order.id, body.order_id, body.buyer.email,
    )
    return {"id": str(order.id), "status": "created"}


class EscrowStatusUpdate(BaseModel):
    escrow_status: str  # held / released / refunded


@router.patch(
    "/escrow-orders/{beckn_order_id}",
    dependencies=[Depends(require_internal_token)],
)
async def update_escrow_status(
    beckn_order_id: str,
    body: EscrowStatusUpdate,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Update escrow status only (called by BAP on RELEASE / REFUND)."""
    from sqlalchemy import select

    existing_q = await db.execute(
        select(Order).where(Order.beckn_order_id == beckn_order_id)
    )
    order = existing_q.scalar_one_or_none()
    if not order:
        raise HTTPException(404, "Order not found")
    try:
        order.escrow_status = EscrowStatus(body.escrow_status)
    except ValueError:
        raise HTTPException(400, f"Invalid escrow_status '{body.escrow_status}'")
    await db.commit()
    return {"id": str(order.id), "escrow_status": order.escrow_status.value}
