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


_DEMO_CUSTOMER_NAMES = [
    ("Sari Kusuma", "sari.kusuma@example.com", True),
    ("Budi Santoso", "budi.santoso@example.com", True),
    ("Maya Anggraini", "maya.a@example.com", True),
    ("Rio Pratama", "rio.pratama@example.com", False),
    ("Nadia Putri", "nadia.putri@example.com", True),
    ("Arif Wijaya", "arif.w@example.com", True),
    ("Lina Hartono", "lina.hartono@example.com", False),
    ("Dimas Saputra", "dimas.s@example.com", True),
    ("Citra Lestari", "citra.l@example.com", True),
    ("Eko Nugroho", "eko.nugroho@example.com", False),
    ("Putri Maharani", "putri.m@example.com", True),
    ("Andi Setiawan", "andi.s@example.com", True),
    ("Dewi Sulistio", "dewi.s@example.com", True),
    ("Rizky Pratama", "rizky.p@example.com", False),
    ("Karina Dewi", "karina.d@example.com", True),
    ("Agus Wibowo", "agus.w@example.com", True),
    ("Sinta Maharani", "sinta.m@example.com", False),
    ("Fajar Hidayat", "fajar.h@example.com", True),
    ("Nia Ramadhani", "nia.r@example.com", True),
    ("Hendra Kurniawan", "hendra.k@example.com", True),
    ("Tika Pertiwi", "tika.p@example.com", False),
    ("Wahyu Santoso", "wahyu.s@example.com", True),
    ("Ratna Sari", "ratna.s@example.com", True),
    ("Bagas Pratama", "bagas.p@example.com", True),
]


def _build_demo_customers() -> list[dict[str, Any]]:
    """Build a credible CRM cohort for the prospect demo."""
    import random
    random.seed(42)
    now = datetime.now(timezone.utc)
    out = []
    seg_plan = (
        ["CHAMPION"] * 4 + ["HIGH_LTV"] * 5 + ["REPEAT"] * 8 + ["NEW"] * 4 +
        ["ONE_TIME"] * 2 + ["AT_RISK"] * 1
    )
    for i, (name, email, is_ba) in enumerate(_DEMO_CUSTOMER_NAMES[:len(seg_plan)]):
        seg = seg_plan[i]
        if seg == "CHAMPION":
            order_count = random.randint(8, 14); ltv = random.randint(2_400_000, 4_800_000); days_since = random.randint(2, 18)
        elif seg == "HIGH_LTV":
            order_count = random.randint(5, 8); ltv = random.randint(1_200_000, 2_300_000); days_since = random.randint(20, 55)
        elif seg == "REPEAT":
            order_count = random.randint(2, 4); ltv = random.randint(500_000, 1_100_000); days_since = random.randint(5, 45)
        elif seg == "NEW":
            order_count = 1; ltv = random.randint(180_000, 480_000); days_since = random.randint(0, 25)
        elif seg == "ONE_TIME":
            order_count = 1; ltv = random.randint(120_000, 350_000); days_since = random.randint(40, 120)
        else:  # AT_RISK
            order_count = random.randint(2, 5); ltv = random.randint(600_000, 1_400_000); days_since = random.randint(95, 180)
        last = now - timedelta(days=days_since)
        first = last - timedelta(days=random.randint(30, 240))
        out.append({
            "email": email,
            "name": name,
            "phone": None,
            "photo_url": None,
            "order_count": order_count,
            "lifetime_value_idr": ltv,
            "first_order_at": first.isoformat(),
            "last_order_at": last.isoformat(),
            "days_since_last_order": days_since,
            "beli_aman_pct": 100.0 if is_ba else 0.0,
            "is_beli_aman_buyer": is_ba,
            "segment": seg,
            "_demo": True,
        })
    return out


@router.get("")
async def list_customers(
    store_id: uuid.UUID = Query(default=DEMO_STORE_ID),
    source: str | None = Query(default=None, description="filter: 'beli_aman' | 'direct' | None"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List unique customers with rolled-up metrics.

    Real customers (rolled up from this store's orders) are merged with mock
    demo customers so the CRM tells a credible story for prospect demos.
    """
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
    real_customers = []
    for r in rows:
        ltv = float(r.lifetime_value or 0)
        ba_pct = (r.beli_aman_count / r.order_count * 100) if r.order_count else 0
        is_ba_buyer = ba_pct >= 50  # majority via Beli Aman
        days_since_last = None
        if r.last_order_at:
            last = r.last_order_at if r.last_order_at.tzinfo else r.last_order_at.replace(tzinfo=timezone.utc)
            days_since_last = (now - last).days

        real_customers.append({
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
            "_demo": False,
        })

    # Real customers first, then mock demo cohort to fill out the CRM
    customers = real_customers + _build_demo_customers()

    # Apply source filter (after merging so totals reflect what's shown)
    if source == "beli_aman":
        customers = [c for c in customers if c["is_beli_aman_buyer"]]
    elif source == "direct":
        customers = [c for c in customers if not c["is_beli_aman_buyer"]]

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
            "real_customer_count": len(real_customers),
        },
        "demo_mode": True,
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
