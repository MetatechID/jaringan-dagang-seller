"""Seller-facing refund API.

GET  /api/refunds                 — list (filterable by status, order_id)
POST /api/refunds/{id}/approve    — approve a PENDING request
POST /api/refunds/{id}/deny       — deny a PENDING request
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.refund import RefundRequest, RefundStatus
from app.services import refund_service

router = APIRouter(prefix="/refunds", tags=["refunds"])


class DecideBody(BaseModel):
    note: str | None = None
    decided_by: str | None = "seller-dashboard"


def _serialize(r: RefundRequest) -> dict:
    return {
        "id": str(r.id),
        "order_id": str(r.order_id),
        "requested_by": r.requested_by,
        "reason_code": r.reason_code.value if r.reason_code else None,
        "reason_text": r.reason_text,
        "requested_amount": r.requested_amount,
        "status": r.status.value if r.status else None,
        "seller_note": r.seller_note,
        "decided_at": r.decided_at.isoformat() if r.decided_at else None,
        "decided_by": r.decided_by,
        "xendit_refund_id": r.xendit_refund_id,
        "error": r.error,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


@router.get("")
async def list_refunds(
    status: str | None = None,
    order_id: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    q = select(RefundRequest).order_by(RefundRequest.created_at.desc())
    if status:
        try:
            q = q.where(RefundRequest.status == RefundStatus(status))
        except ValueError:
            raise HTTPException(400, f"unknown status '{status}'")
    if order_id:
        try:
            q = q.where(RefundRequest.order_id == uuid.UUID(order_id))
        except ValueError:
            raise HTTPException(400, "order_id must be a UUID")
    rows = (await db.execute(q)).scalars().all()
    return {"data": [_serialize(r) for r in rows]}


@router.get("/{refund_id}")
async def get_refund(refund_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    r = await db.get(RefundRequest, refund_id)
    if r is None:
        raise HTTPException(404, "Refund not found")
    return {"data": _serialize(r)}


@router.post("/{refund_id}/approve")
async def approve_refund(
    refund_id: uuid.UUID,
    body: DecideBody,
    db: AsyncSession = Depends(get_db),
):
    try:
        r = await refund_service.approve(
            db, refund_id,
            decided_by=body.decided_by or "seller-dashboard",
            note=body.note,
        )
    except refund_service.RefundError as e:
        raise HTTPException(400, str(e))
    return {"data": _serialize(r)}


@router.post("/{refund_id}/deny")
async def deny_refund(
    refund_id: uuid.UUID,
    body: DecideBody,
    db: AsyncSession = Depends(get_db),
):
    try:
        r = await refund_service.deny(
            db, refund_id,
            decided_by=body.decided_by or "seller-dashboard",
            note=body.note,
        )
    except refund_service.RefundError as e:
        raise HTTPException(400, str(e))
    return {"data": _serialize(r)}
