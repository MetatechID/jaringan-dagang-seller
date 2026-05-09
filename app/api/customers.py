"""Customer 360 endpoints for the seller dashboard.

Aggregates the orders table by buyer_email — each buyer gets:
- identity (name, email, phone, photo if Beli Aman)
- order count + lifetime value (in IDR)
- first/last order timestamps
- source mix (% via Beli Aman vs direct)
- segment (auto-computed: NEW, REPEAT, HIGH_LTV, AT_RISK, CHAMPION)
- full order history
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.order import Order, OrderStatus

router = APIRouter(prefix="/customers", tags=["customers"])


DEMO_STORE_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _segment_for(total_orders: int, total_spent: int, days_since_last: int | None) -> str:
    """Auto-classify a buyer."""
    if total_orders == 0:
        return "INACTIVE"
    if total_orders == 1:
        if days_since_last is not None and days_since_last < 30:
            return "NEW"
        return "ONE_TIME"
    if total_spent >= 1_000_000:
        if days_since_last is not None and days_since_last < 60:
            return "CHAMPION"
        return "HIGH_LTV"
    if days_since_last is not None and days_since_last > 90:
        return "AT_RISK"
    return "REPEAT"


@router.get("")
async def list_customers(
    store_id: uuid.UUID = Query(default=DEMO_STORE_ID),
    source: str | None = Query(default=None, description="filter: 'beli_aman' | 'direct' | None"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List unique customers with rolled-up metrics."""
    # Group orders by buyer_email
    stmt = (
        select(
            Order.buyer_email,
            func.count(Order.id).label("order_count"),
            func.sum(Order.total).label("lifetime_value"),
            func.min(Order.created_at).label("first_order_at"),
            func.max(Order.created_at).label("last_order_at"),
            func.max(Order.buyer_name).label("buyer_name"),
            func.max(Order.buyer_phone).label("buyer_phone"),
            func.max(Order.buyer_photo_url).label("buyer_photo_url"),
            func.sum(case((Order.bap_id.isnot(None), 1), else_=0)).label("beli_aman_count"),
        )
        .where(Order.store_id == store_id, Order.buyer_email.isnot(None))
        .group_by(Order.buyer_email)
        .order_by(func.max(Order.created_at).desc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    now = datetime.now(timezone.utc)
    customers = []
    for r in rows:
        ltv = float(r.lifetime_value or 0)
        ba_pct = (r.beli_aman_count / r.order_count * 100) if r.order_count else 0
        is_ba_buyer = ba_pct >= 50  # majority via Beli Aman
        days_since_last = None
        if r.last_order_at:
            last = r.last_order_at if r.last_order_at.tzinfo else r.last_order_at.replace(tzinfo=timezone.utc)
            days_since_last = (now - last).days

        if source == "beli_aman" and not is_ba_buyer:
            continue
        if source == "direct" and is_ba_buyer:
            continue

        customers.append({
            "email": r.buyer_email,
            "name": r.buyer_name or "Unknown",
            "phone": r.buyer_phone,
            "photo_url": r.buyer_photo_url,
            "order_count": int(r.order_count),
            "lifetime_value_idr": int(ltv),
            "first_order_at": r.first_order_at.isoformat() if r.first_order_at else None,
            "last_order_at": r.last_order_at.isoformat() if r.last_order_at else None,
            "days_since_last_order": days_since_last,
            "beli_aman_pct": round(ba_pct, 1),
            "is_beli_aman_buyer": is_ba_buyer,
            "segment": _segment_for(int(r.order_count), int(ltv), days_since_last),
        })

    # Top-line metrics
    total_customers = len(customers)
    ba_customers = sum(1 for c in customers if c["is_beli_aman_buyer"])
    total_ltv = sum(c["lifetime_value_idr"] for c in customers)

    return {
        "data": customers,
        "summary": {
            "total_customers": total_customers,
            "beli_aman_customers": ba_customers,
            "direct_customers": total_customers - ba_customers,
            "beli_aman_pct": round(ba_customers / total_customers * 100, 1) if total_customers else 0,
            "total_lifetime_value_idr": total_ltv,
            "average_lifetime_value_idr": int(total_ltv / total_customers) if total_customers else 0,
        },
    }


@router.get("/{email}")
async def get_customer(
    email: str,
    store_id: uuid.UUID = Query(default=DEMO_STORE_ID),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Customer 360 — full identity + every order placed."""
    # Aggregate
    agg_stmt = (
        select(
            func.count(Order.id),
            func.sum(Order.total),
            func.min(Order.created_at),
            func.max(Order.created_at),
            func.max(Order.buyer_name),
            func.max(Order.buyer_phone),
            func.max(Order.buyer_photo_url),
            func.sum(case((Order.bap_id.isnot(None), 1), else_=0)),
        )
        .where(Order.store_id == store_id, Order.buyer_email == email)
    )
    agg = (await db.execute(agg_stmt)).one()
    if not agg[0]:
        raise HTTPException(404, f"No customer with email {email}")

    order_count, total_spent, first_at, last_at, name, phone, photo, ba_count = agg
    total_spent = float(total_spent or 0)
    ba_pct = (ba_count / order_count * 100) if order_count else 0

    # All orders
    orders_stmt = (
        select(Order)
        .where(Order.store_id == store_id, Order.buyer_email == email)
        .order_by(Order.created_at.desc())
    )
    orders = (await db.execute(orders_stmt)).scalars().all()

    now = datetime.now(timezone.utc)
    days_since_last = None
    if last_at:
        last = last_at if last_at.tzinfo else last_at.replace(tzinfo=timezone.utc)
        days_since_last = (now - last).days

    return {
        "data": {
            "email": email,
            "name": name or "Unknown",
            "phone": phone,
            "photo_url": photo,
            "order_count": int(order_count),
            "lifetime_value_idr": int(total_spent),
            "first_order_at": first_at.isoformat() if first_at else None,
            "last_order_at": last_at.isoformat() if last_at else None,
            "days_since_last_order": days_since_last,
            "beli_aman_pct": round(ba_pct, 1),
            "is_beli_aman_buyer": ba_pct >= 50,
            "segment": _segment_for(int(order_count), int(total_spent), days_since_last),
            "orders": [
                {
                    "id": str(o.id),
                    "beckn_order_id": o.beckn_order_id,
                    "status": o.status.value if o.status else None,
                    "total": float(o.total or 0),
                    "currency": o.currency,
                    "created_at": o.created_at.isoformat() if o.created_at else None,
                    "bap_id": o.bap_id,
                    "escrow_status": o.escrow_status.value if o.escrow_status else "none",
                    "items": o.items,
                    "shipping_address": o.shipping_address,
                }
                for o in orders
            ],
        }
    }
