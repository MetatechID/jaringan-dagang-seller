"""Seller-facing Score (reputation) REST API (Task A6).

Two endpoints:

* ``POST /api/score/compute`` (admin-token-gated)
    — operator triggers score computation for a store + period.
* ``GET  /api/score/{store_id}`` (Firebase + can_access_store)
    — returns the latest ScoreSnapshot for the store.

v1 doesn't expose a daily worker that auto-runs the compute — the
operator runs ``POST /compute`` after each day's settlement window.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import can_access_store, get_current_user
from app.database import get_db
from app.models.score import ScoreSnapshot
from app.models.user import User
from app.services import score_service

router = APIRouter(prefix="/score", tags=["score"])


def _check_admin(token: str) -> None:
    expected = os.environ.get("ADMIN_MIGRATE_TOKEN", "")
    if not expected:
        raise HTTPException(503, "Admin disabled (set ADMIN_MIGRATE_TOKEN env)")
    if token != expected:
        raise HTTPException(401, "Bad X-Admin-Token")


class ComputeBody(BaseModel):
    store_id: str = Field(..., description="Target store UUID.")
    period_start: datetime = Field(
        ...,
        description="Window start (UTC); inclusive.",
    )
    period_end: datetime = Field(
        ...,
        description="Window end (UTC); exclusive.",
    )


def _serialize(s: ScoreSnapshot) -> dict:
    return {
        "id": str(s.id),
        "store_id": str(s.store_id),
        "period_start": s.period_start.isoformat() if s.period_start else None,
        "period_end": s.period_end.isoformat() if s.period_end else None,
        "completion_rate": float(s.completion_rate),
        "return_rate": float(s.return_rate),
        "avg_response_hours": (
            float(s.avg_response_hours) if s.avg_response_hours is not None else None
        ),
        "resolution_time_hours": (
            float(s.resolution_time_hours)
            if s.resolution_time_hours is not None
            else None
        ),
        "rating_avg": float(s.rating_avg),
        "band": s.band,
        "total_orders": s.total_orders,
        "completed_orders": s.completed_orders,
        "refunded_orders": s.refunded_orders,
        "last_computed_at": (
            s.last_computed_at.isoformat() if s.last_computed_at else None
        ),
    }


@router.post("/compute")
async def compute(
    body: ComputeBody,
    x_admin_token: str = Header(default=""),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Compute + upsert a ScoreSnapshot for the given store + period.

    Admin-token-gated (operator-only). Returns the persisted snapshot.
    """
    _check_admin(x_admin_token)
    try:
        sid = uuid.UUID(body.store_id)
    except (ValueError, TypeError):
        raise HTTPException(400, "store_id must be a UUID")

    try:
        snap = await score_service.compute_for_store(
            db,
            store_id=sid,
            period_start=body.period_start,
            period_end=body.period_end,
        )
    except score_service.ScoreError as exc:
        raise HTTPException(400, str(exc))
    await db.commit()
    await db.refresh(snap)
    return _serialize(snap)


@router.get("/{store_id}")
async def get_latest(
    store_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return the latest ScoreSnapshot for the store.

    Auth: Firebase user must have access to the store (``can_access_store``).
    Returns 404 if no snapshot has been computed yet.
    """
    try:
        sid = uuid.UUID(store_id)
    except (ValueError, TypeError):
        raise HTTPException(400, "store_id must be a UUID")
    if not await can_access_store(db, user, sid):
        raise HTTPException(403, "no access to this store")

    snap = (await db.execute(
        select(ScoreSnapshot)
        .where(ScoreSnapshot.store_id == sid)
        .order_by(desc(ScoreSnapshot.period_start))
        .limit(1)
    )).scalar_one_or_none()
    if snap is None:
        raise HTTPException(404, "no score snapshot for this store yet")
    return _serialize(snap)
