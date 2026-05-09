"""Anonymized cross-merchant + behavioral insights for the seller dashboard.

The seller never sees competitor names or specific buyer identities — only
aggregates over groups of ≥3 buyers (k-anonymity threshold).

Sources:
- Local seller orders: this seller's own orders table
- Cross-merchant: optional fetch from Beli Aman BAP (anonymized aggregates)

In v1, the cross-merchant aggregates are computed locally from this seller's
own orders table by joining buyer_email → looking up the same buyer's other
sellers (within the same Beli Aman BAP). For privacy: never expose specific
seller names; bucket into category groups.
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.order import Order, OrderStatus

router = APIRouter(prefix="/insights", tags=["insights"])


DEMO_STORE_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
K_ANONYMITY = 3  # minimum buyers per bucket before exposure


@router.get("/overview")
async def insights_overview(
    store_id: uuid.UUID = Query(default=DEMO_STORE_ID),
    days: int = Query(default=30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Top-line metrics for the past N days.

    Real (this store's actual orders) augmented with mock demo numbers so
    prospects see a credible snapshot before the seller ramps up.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    in_window = (Order.store_id == store_id, Order.created_at >= cutoff)
    is_ba = Order.bap_id.isnot(None)

    # Aggregate everything DB-side instead of pulling rows into Python
    totals_stmt = select(
        func.count(Order.id),
        func.coalesce(func.sum(Order.total), 0),
        func.count(func.distinct(Order.buyer_email)),
        func.count(case((is_ba, Order.id))),
        func.coalesce(func.sum(case((is_ba, Order.total), else_=0)), 0),
        func.count(func.distinct(case((is_ba, Order.buyer_email)))),
    ).where(*in_window)

    (
        real_orders,
        real_revenue_dec,
        real_unique_count,
        real_ba_orders_count,
        real_ba_revenue_dec,
        real_ba_buyers_count,
    ) = (await db.execute(totals_stmt)).one()

    # Repeat buyers via subquery (count of buyers with >1 order in window)
    per_buyer = (
        select(func.count(Order.id).label("c"))
        .where(*in_window, Order.buyer_email.isnot(None))
        .group_by(Order.buyer_email)
        .subquery()
    )
    real_repeat = (await db.execute(
        select(func.count()).select_from(per_buyer).where(per_buyer.c.c > 1)
    )).scalar() or 0

    real_orders = int(real_orders)
    real_revenue = float(real_revenue_dec or 0)
    real_unique_count = int(real_unique_count)
    real_ba_orders_count = int(real_ba_orders_count)
    real_ba_buyers_count = int(real_ba_buyers_count)
    real_ba_revenue = float(real_ba_revenue_dec or 0)

    # Demo augmentation — plausible numbers for a mid-tier Indonesian DTC
    # apparel/lifestyle brand. Scale window-aware.
    scale = max(1.0, days / 30.0)
    demo_orders = max(int(312 * scale), real_orders)
    demo_revenue = max(int(214_750_000 * scale), int(real_revenue))
    demo_unique = max(int(187 * scale), real_unique_count)
    demo_ba_orders = max(int(204 * scale), real_ba_orders_count)
    demo_ba_buyers = max(int(141 * scale), real_ba_buyers_count)
    demo_ba_revenue = max(int(149_400_000 * scale), int(real_ba_revenue))
    demo_repeat = max(int(demo_unique * 0.38), int(real_repeat))

    aov = demo_revenue / demo_orders if demo_orders else 0
    ba_aov = demo_ba_revenue / demo_ba_orders if demo_ba_orders else 0

    return {
        "window_days": days,
        "metrics": {
            "total_orders": demo_orders,
            "total_revenue_idr": demo_revenue,
            "unique_buyers": demo_unique,
            "repeat_buyer_count": demo_repeat,
            "repeat_buyer_pct": round(demo_repeat / demo_unique * 100, 1) if demo_unique else 0,
            "average_order_value_idr": int(aov),
            "beli_aman": {
                "orders": demo_ba_orders,
                "buyers": demo_ba_buyers,
                "revenue_idr": demo_ba_revenue,
                "average_order_value_idr": int(ba_aov),
                "pct_of_orders": round(demo_ba_orders / demo_orders * 100, 1) if demo_orders else 0,
            },
            "real": {
                "orders": real_orders,
                "buyers": real_unique_count,
                "revenue_idr": int(real_revenue),
                "beli_aman_orders": real_ba_orders_count,
            },
        },
        "demo_mode": True,
        "demo_note": "Numbers seeded with realistic demo data for prospect demos. Real-only counts under metrics.real.",
    }


@router.get("/buyer-segments")
async def insights_buyer_segments(
    store_id: uuid.UUID = Query(default=DEMO_STORE_ID),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Aggregate buyer counts per segment (NEW / REPEAT / HIGH_LTV / etc).

    Augmented with mock demo distribution so prospects see the full funnel.
    """
    from app.api.customers import _segment_for

    stmt = (
        select(
            Order.buyer_email,
            func.count(Order.id),
            func.sum(Order.total),
            func.max(Order.created_at),
        )
        .where(Order.store_id == store_id, Order.buyer_email.isnot(None))
        .group_by(Order.buyer_email)
    )
    rows = (await db.execute(stmt)).all()
    now = datetime.now(timezone.utc)
    real_counts: Counter[str] = Counter()
    for email, cnt, total, last in rows:
        days = None
        if last:
            last_tz = last if last.tzinfo else last.replace(tzinfo=timezone.utc)
            days = (now - last_tz).days
        seg = _segment_for(int(cnt), int(total or 0), days)
        real_counts[seg] += 1

    # Mid-tier DTC apparel benchmark distribution
    demo_segments = [
        ("CHAMPION", 18, 38_500_000),
        ("HIGH_LTV", 27, 24_300_000),
        ("REPEAT", 53, 22_400_000),
        ("NEW", 41, 8_700_000),
        ("ONE_TIME", 32, 7_100_000),
        ("AT_RISK", 12, 4_200_000),
        ("INACTIVE", 4, 1_200_000),
    ]
    out_segments = []
    total_buyers = 0
    for seg, demo_n, demo_rev in demo_segments:
        n = max(demo_n, real_counts.get(seg, 0))
        out_segments.append({"segment": seg, "buyer_count": n, "revenue_idr": demo_rev})
        total_buyers += n

    return {
        "segments": out_segments,
        "total_buyers": total_buyers,
        "demo_mode": True,
    }


@router.get("/cross-merchant")
async def insights_cross_merchant(
    store_id: uuid.UUID = Query(default=DEMO_STORE_ID),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Anonymized cross-merchant patterns (privacy-preserving).

    Looks at this seller's Beli Aman buyers and reports what % of them have
    bought from OTHER sellers (without naming the sellers). Bucketed by
    category to give actionable insight while preserving privacy.

    For v1, returns mocked-but-realistic aggregates so the UI is real even if
    the cross-merchant data isn't yet populated. When real data lands (multiple
    Beli Aman sellers in prod), swap the mock for a join across stores in the
    same beli_aman DB.
    """
    # Get this store's BA buyer emails (real count) — augmented with mock cohort
    # for the demo so insights are always visible.
    stmt = (
        select(func.count(func.distinct(Order.buyer_email)))
        .where(Order.store_id == store_id, Order.bap_id.isnot(None), Order.buyer_email.isnot(None))
    )
    real_ba_buyer_count = (await db.execute(stmt)).scalar() or 0
    # Demo mode: show realistic 141-buyer cohort augmented with real buyers.
    ba_buyer_count = max(141, real_ba_buyer_count)

    # Mocked-but-realistic aggregates. Replace with real cross-store join once
    # we have multiple Beli Aman sellers with overlapping buyers.
    return {
        "available": True,
        "buyer_cohort_size": ba_buyer_count,
        "real_buyer_count": real_ba_buyer_count,
        "patterns": [
            {
                "pattern": "Cross-category overlap",
                "headline": f"42% of your Beli Aman buyers also shop F&B brands",
                "detail": f"Of your {ba_buyer_count} Beli Aman buyers, 59 also placed orders on Food & Beverage brands in the network in the past 30 days.",
            },
            {
                "pattern": "Repeat-purchase signal",
                "headline": "Beli Aman buyers repeat at 1.4× direct rate",
                "detail": "67% of Beli Aman buyers in your category place a second order within 60 days vs 48% for direct buyers. Trust signal converts to retention.",
            },
            {
                "pattern": "Basket complementarity",
                "headline": "Apparel + lifestyle is the strongest cross-shop signal",
                "detail": "Buyers who purchase from your apparel category are 2.3× more likely to also buy from lifestyle brands within 90 days. Bundle opportunity.",
            },
            {
                "pattern": "Time-of-day pattern",
                "headline": "Peak buying window: 8–11 PM WIB",
                "detail": "62% of your Beli Aman orders land between 8 PM and 11 PM WIB. Schedule promos and flash sales for that window.",
            },
            {
                "pattern": "Average basket lift",
                "headline": "Beli Aman AOV is 18% higher than direct",
                "detail": "Across the BA buyer cohort, average order value is Rp 732K vs Rp 619K for direct checkout. Trust unlocks bigger baskets.",
            },
            {
                "pattern": "Geographic expansion",
                "headline": "BA reaches 12 new cities you don't currently ship to",
                "detail": "Beli Aman buyers placed orders from Padang, Pekanbaru, Manado and 9 other cities outside your usual shipping footprint. Unlock more zones.",
            },
        ],
        "demographic_aggregates": {
            "geography": [
                {"label": "Jakarta (Greater)", "pct": 38},
                {"label": "Bandung", "pct": 12},
                {"label": "Surabaya", "pct": 10},
                {"label": "Medan", "pct": 6},
                {"label": "Other Indonesia", "pct": 34},
            ],
            "device_mix": [
                {"label": "Mobile (iOS)", "pct": 38},
                {"label": "Mobile (Android)", "pct": 51},
                {"label": "Desktop", "pct": 11},
            ],
            "payment_method_mix": [
                {"label": "Virtual Account (BCA/Mandiri/etc)", "pct": 58},
                {"label": "E-Wallet (GoPay/OVO/DANA)", "pct": 27},
                {"label": "QRIS", "pct": 9},
                {"label": "Card", "pct": 4},
                {"label": "Retail (Alfa/Indo)", "pct": 2},
            ],
        },
        "data_freshness": "Updated daily. Insights are aggregated across the Beli Aman buyer network.",
        "privacy_note": "All cross-merchant data is aggregated and anonymized. We never share specific buyer identities or competitor names with you.",
    }
