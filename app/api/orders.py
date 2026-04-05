"""Internal REST API for order management (seller dashboard)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.order import OrderStatus
from app.services import order_service

router = APIRouter(prefix="/orders", tags=["orders"])


DEMO_STORE_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


class OrderStatusUpdate(BaseModel):
    status: OrderStatus


@router.get("")
async def list_orders(
    store_id: uuid.UUID = Query(default=DEMO_STORE_ID),
    status: OrderStatus | None = None,
    offset: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """List orders for a store."""
    orders = await order_service.list_orders(
        db, store_id, status=status, offset=offset, limit=limit
    )
    return {"data": [_serialize(o) for o in orders]}


@router.get("/{order_id}")
async def get_order(
    order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a single order by ID."""
    order = await order_service.get_order(db, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return {"data": _serialize(order)}


@router.put("/{order_id}/status")
async def update_order_status(
    order_id: uuid.UUID,
    body: OrderStatusUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update the order status (validates transitions)."""
    try:
        order = await order_service.update_order_status(
            db, order_id, body.status
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except order_service.InvalidOrderTransition as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return {"data": _serialize(order)}


# ------------------------------------------------------------------
# Serialisation helper
# ------------------------------------------------------------------


def _serialize(order) -> dict[str, Any]:
    """Serialize an Order ORM object to a dict."""
    result: dict[str, Any] = {
        "id": str(order.id),
        "store_id": str(order.store_id),
        "beckn_order_id": order.beckn_order_id,
        "buyer_name": order.buyer_name,
        "buyer_phone": order.buyer_phone,
        "buyer_email": order.buyer_email,
        "billing_address": order.billing_address,
        "shipping_address": order.shipping_address,
        "status": order.status.value if order.status else None,
        "total": float(order.total) if order.total else 0,
        "currency": order.currency,
        "items": order.items,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "updated_at": order.updated_at.isoformat() if order.updated_at else None,
    }

    if order.payment:
        p = order.payment
        result["payment"] = {
            "id": str(p.id),
            "xendit_invoice_id": p.xendit_invoice_id,
            "amount": float(p.amount),
            "method": p.method,
            "channel": p.channel,
            "status": p.status.value if p.status else None,
            "paid_at": p.paid_at.isoformat() if p.paid_at else None,
        }

    if order.fulfillment:
        f = order.fulfillment
        result["fulfillment"] = {
            "id": str(f.id),
            "type": f.type,
            "courier_code": f.courier_code,
            "courier_service": f.courier_service,
            "awb_number": f.awb_number,
            "status": f.status.value if f.status else None,
            "tracking_url": f.tracking_url,
            "shipping_cost": float(f.shipping_cost) if f.shipping_cost else None,
        }

    return result
