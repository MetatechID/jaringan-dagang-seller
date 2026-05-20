"""Refund workflow: create, approve, deny, finalize.

Flow:
  1. Buyer sends Beckn /update with descriptor.code=refund_request →
     create_from_beckn_update() makes a PENDING RefundRequest.
  2. Seller dashboard POST /api/refunds/{id}/approve → approve():
     - status = APPROVED
     - call Xendit refund API → xendit_refund_id (or set status=FAILED + error)
     - on success: flip order escrow_status to REFUNDED, payment status to REFUNDED
     - emit Beckn /on_update {refund_approved} to BAP
  3. Seller dashboard POST /api/refunds/{id}/deny → deny():
     - status = DENIED
     - emit Beckn /on_update {refund_denied} with seller_note
  4. Xendit webhook /webhooks/xendit?event=refund.succeeded → settle():
     - status = REFUNDED
     - emit Beckn /on_update {refund_settled}
"""

from __future__ import annotations

import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.order import Order, EscrowStatus
from app.models.payment import PaymentRecord, PaymentStatus
from app.models.refund import RefundReason, RefundRequest, RefundStatus
from app.models.store import Store

# Make beckn-protocol importable
_proto_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "packages", "beckn-protocol")
)
if _proto_path not in sys.path:
    sys.path.insert(0, _proto_path)

logger = logging.getLogger(__name__)


class RefundError(Exception):
    pass


async def create_from_beckn_update(
    db: AsyncSession,
    *,
    order_beckn_id: str,
    reason_code: str | None,
    reason_text: str | None,
    requested_amount: int | None,
) -> RefundRequest | None:
    """Idempotent: returns existing open request if one exists, else creates."""
    res = await db.execute(
        select(Order).where(Order.beckn_order_id == order_beckn_id)
    )
    order = res.scalar_one_or_none()
    if order is None:
        logger.warning("refund request for unknown order %s", order_beckn_id)
        return None

    existing = (await db.execute(
        select(RefundRequest)
        .where(RefundRequest.order_id == order.id)
        .where(RefundRequest.status.in_([RefundStatus.PENDING, RefundStatus.APPROVED]))
    )).scalar_one_or_none()
    if existing:
        return existing

    try:
        reason = RefundReason(reason_code) if reason_code else RefundReason.OTHER
    except ValueError:
        reason = RefundReason.OTHER

    amount = int(requested_amount) if requested_amount else int(order.total or 0)

    req = RefundRequest(
        order_id=order.id,
        requested_by="buyer",
        reason_code=reason,
        reason_text=reason_text,
        requested_amount=amount,
        status=RefundStatus.PENDING,
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)
    return req


# ONDC IGM v1 ITEM sub-category -> internal RefundReason mapping.
# Mirrors the buyer's services/igm._SUB_TO_REASON so both sides agree on
# the reason taxonomy.
_IGM_SUB_TO_REASON: dict[str, RefundReason] = {
    "ITM01": RefundReason.ITEM_NOT_RECEIVED,
    "ITM02": RefundReason.ITEM_NOT_RECEIVED,
    "ITM03": RefundReason.OTHER,        # quantity
    "ITM04": RefundReason.WRONG_ITEM,   # item mismatch
    "ITM05": RefundReason.ITEM_DAMAGED, # quality issue
}


async def create_from_beckn_issue(
    db: AsyncSession,
    *,
    order_beckn_id: str,
    sub_category: str,
    reason_text: str | None,
    requested_amount: int | None,
    bap_issue_id: str,
) -> RefundRequest | None:
    """ONDC IGM /issue -> RefundRequest.

    Idempotent on bap_issue_id: if we already created a RefundRequest
    for this Issue id (e.g. BAP retried /issue with the same message_id
    after our ACK was lost), return the existing row.

    Returns ``None`` if the referenced order doesn't exist on the BPP
    side (the handler turns this into a 90005 error).
    """
    res = await db.execute(
        select(Order).where(Order.beckn_order_id == order_beckn_id)
    )
    order = res.scalar_one_or_none()
    if order is None:
        logger.warning(
            "/issue against unknown order %s (issue %s)",
            order_beckn_id, bap_issue_id,
        )
        return None

    # Idempotent on the BAP-issued issue_id: re-issue with same id is a
    # no-op return of the existing RefundRequest.
    #
    # Task A6 promoted ``bap_issue_id`` to a dedicated indexed column.
    # The lookup prefers the new column; the legacy seller_note /
    # error stashes remain a transitional fallback for rows created
    # before ``scripts/add-refund-bap-issue-id-column.py`` back-filled.
    existing = (await db.execute(
        select(RefundRequest)
        .where(RefundRequest.order_id == order.id)
        .where(
            (RefundRequest.bap_issue_id == bap_issue_id)
            | (RefundRequest.error == f"bap_issue_id={bap_issue_id}")
            | (RefundRequest.seller_note == f"bap_issue_id={bap_issue_id}")
        )
    )).scalar_one_or_none()
    if existing:
        # Back-fill the dedicated column for legacy rows we find via the
        # seller_note / error stash so subsequent reads use the indexed
        # path. Cheap (no extra round-trip), idempotent.
        if existing.bap_issue_id is None:
            existing.bap_issue_id = bap_issue_id
            await db.commit()
        return existing

    reason = _IGM_SUB_TO_REASON.get(sub_category, RefundReason.OTHER)
    amount = int(requested_amount) if requested_amount else int(order.total or 0)

    req = RefundRequest(
        order_id=order.id,
        requested_by="buyer",
        reason_code=reason,
        reason_text=reason_text,
        requested_amount=amount,
        status=RefundStatus.PENDING,
        # Write to BOTH the dedicated indexed column AND seller_note. The
        # latter is the A5-era back-compat path for any downstream reader
        # that still parses the stash (Task A6 follow-up: remove once all
        # readers migrate to the column).
        bap_issue_id=bap_issue_id,
        seller_note=f"bap_issue_id={bap_issue_id}",
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)
    return req


async def approve(
    db: AsyncSession, refund_id: uuid.UUID, *, decided_by: str, note: str | None = None,
) -> RefundRequest:
    req = await db.get(RefundRequest, refund_id)
    if req is None:
        raise RefundError(f"refund {refund_id} not found")
    if req.status != RefundStatus.PENDING:
        raise RefundError(f"cannot approve from status={req.status}")

    req.status = RefundStatus.APPROVED
    req.decided_at = datetime.now(timezone.utc)
    req.decided_by = decided_by
    if note:
        req.seller_note = note
    await db.commit()

    payment = (await db.execute(
        select(PaymentRecord).where(PaymentRecord.order_id == req.order_id)
    )).scalar_one_or_none()

    # Call Xendit refund (mock if no key)
    xendit_key = settings.XENDIT_SECRET_KEY
    if xendit_key and payment and payment.xendit_invoice_id:
        try:
            async with httpx.AsyncClient(auth=(xendit_key, ""), timeout=15.0) as c:
                r = await c.post(
                    f"{settings.XENDIT_API_BASE}/refunds",
                    json={
                        "payment_id": payment.xendit_invoice_id,
                        "amount": req.requested_amount,
                        "reason": req.reason_code.value,
                    },
                )
                r.raise_for_status()
                req.xendit_refund_id = r.json().get("id")
        except Exception as e:
            req.error = repr(e)[:1000]
            await db.commit()
            logger.exception("Xendit refund failed for %s", req.id)
            await _emit_refund_status(db, req, "refund_approved")
            return req
    else:
        # mock mode — synthesize refund id and immediately flip to REFUNDED
        req.xendit_refund_id = f"mock-refund-{uuid.uuid4().hex[:12]}"

    # Optimistically flip escrow + payment to REFUNDED on approve (Xendit
    # webhook confirms via settle()).
    order = await db.get(Order, req.order_id)
    if order is not None:
        order.escrow_status = EscrowStatus.REFUNDED
    if payment is not None:
        payment.status = PaymentStatus.REFUNDED
    await db.commit()
    await _emit_refund_status(db, req, "refund_approved")
    return req


async def deny(
    db: AsyncSession, refund_id: uuid.UUID, *, decided_by: str, note: str | None = None,
) -> RefundRequest:
    req = await db.get(RefundRequest, refund_id)
    if req is None:
        raise RefundError(f"refund {refund_id} not found")
    if req.status != RefundStatus.PENDING:
        raise RefundError(f"cannot deny from status={req.status}")
    req.status = RefundStatus.DENIED
    req.seller_note = note
    req.decided_at = datetime.now(timezone.utc)
    req.decided_by = decided_by
    await db.commit()
    await _emit_refund_status(db, req, "refund_denied")
    return req


async def settle(db: AsyncSession, xendit_refund_id: str) -> RefundRequest | None:
    """Called from Xendit refund.succeeded webhook."""
    req = (await db.execute(
        select(RefundRequest).where(RefundRequest.xendit_refund_id == xendit_refund_id)
    )).scalar_one_or_none()
    if req is None:
        return None
    req.status = RefundStatus.REFUNDED
    await db.commit()
    await _emit_refund_status(db, req, "refund_settled")
    return req


async def respond_to_issue(
    db: AsyncSession,
    refund_id: uuid.UUID,
    *,
    action: str,
    note: str = "",
    decided_by: str = "seller-dashboard",
) -> RefundRequest:
    """ONDC IGM /on_issue response — sent by the seller agent.

    Args:
        action: one of ``PROCESSING``, ``RESOLVED``, ``REJECTED``.

    Behaviour:
        - PROCESSING: no Xendit call, no state change beyond noting
                      the agent acknowledged. Emits a /on_issue with
                      respondent_action=PROCESSING.
        - RESOLVED:   calls Xendit refund (or mock), flips RefundRequest
                      to APPROVED -> REFUNDED, flips Order to REFUNDED.
                      Emits /on_issue with respondent_action=RESOLVED.
        - REJECTED:   marks RefundRequest=DENIED with the reason note.
                      Emits /on_issue with respondent_action=REJECTED.
    """
    if action not in {"PROCESSING", "RESOLVED", "REJECTED"}:
        raise RefundError(f"unknown IGM respondent_action {action!r}")

    req = await db.get(RefundRequest, refund_id)
    if req is None:
        raise RefundError(f"refund {refund_id} not found")

    bap_issue_id = _extract_bap_issue_id(req)

    if action == "PROCESSING":
        # Already PENDING — no DB mutation. Just emit /on_issue.
        await _emit_on_issue(
            db, req,
            action="PROCESSING",
            short_desc=note or "Issue acknowledged; processing.",
            bap_issue_id=bap_issue_id,
        )
        return req

    if action == "REJECTED":
        if req.status != RefundStatus.PENDING:
            raise RefundError(
                f"cannot REJECT from status={req.status.value}"
            )
        req.status = RefundStatus.DENIED
        req.seller_note = note or req.seller_note
        req.decided_at = datetime.now(timezone.utc)
        req.decided_by = decided_by
        await db.commit()
        await _emit_on_issue(
            db, req,
            action="REJECTED",
            short_desc=note or "Refund rejected by seller.",
            long_desc=note,
            bap_issue_id=bap_issue_id,
        )
        return req

    # RESOLVED — call Xendit, settle, emit.
    if req.status not in (RefundStatus.PENDING, RefundStatus.APPROVED):
        raise RefundError(f"cannot RESOLVE from status={req.status.value}")

    req.status = RefundStatus.APPROVED
    req.decided_at = datetime.now(timezone.utc)
    req.decided_by = decided_by
    if note:
        req.seller_note = note
    await db.commit()

    payment = (await db.execute(
        select(PaymentRecord).where(PaymentRecord.order_id == req.order_id)
    )).scalar_one_or_none()

    xendit_key = settings.XENDIT_SECRET_KEY
    if xendit_key and payment and payment.xendit_invoice_id:
        try:
            async with httpx.AsyncClient(
                auth=(xendit_key, ""), timeout=15.0
            ) as c:
                r = await c.post(
                    f"{settings.XENDIT_API_BASE}/refunds",
                    json={
                        "payment_id": payment.xendit_invoice_id,
                        "amount": req.requested_amount,
                        "reason": req.reason_code.value,
                    },
                )
                r.raise_for_status()
                req.xendit_refund_id = r.json().get("id")
        except Exception as e:
            req.error = repr(e)[:1000]
            await db.commit()
            logger.exception("Xendit refund failed for %s", req.id)
            await _emit_on_issue(
                db, req,
                action="RESOLVED",
                short_desc="Refund initiated; payment platform error.",
                long_desc=note,
                bap_issue_id=bap_issue_id,
            )
            return req
    else:
        # Mock mode — synthesize refund id.
        req.xendit_refund_id = f"mock-refund-{uuid.uuid4().hex[:12]}"

    # Flip escrow + payment + refund to REFUNDED optimistically (the
    # Xendit webhook will confirm via settle()).
    order = await db.get(Order, req.order_id)
    if order is not None:
        order.escrow_status = EscrowStatus.REFUNDED
    if payment is not None:
        payment.status = PaymentStatus.REFUNDED
    req.status = RefundStatus.REFUNDED
    await db.commit()

    await _emit_on_issue(
        db, req,
        action="RESOLVED",
        short_desc=note or "Refund issued.",
        long_desc=note,
        bap_issue_id=bap_issue_id,
    )
    return req


def _extract_bap_issue_id(req: RefundRequest) -> str | None:
    """Pull bap_issue_id back out, preferring the dedicated column.

    Task A6 added a dedicated ``RefundRequest.bap_issue_id`` indexed
    column. Reads prefer it; if missing (pre-A6 rows that haven't yet
    been back-filled by ``scripts/add-refund-bap-issue-id-column.py``)
    we fall back to the A5-era ``seller_note=bap_issue_id=<uuid>``
    stash, and finally the ``error`` stash (oldest format).

    The seller_note + error fallbacks should be removed once the live
    DB has been back-filled and we have observed zero non-column hits
    for one settlement window (A6 follow-up).
    """
    if req.bap_issue_id:
        return req.bap_issue_id
    note = req.seller_note or ""
    if note.startswith("bap_issue_id="):
        return note.split("=", 1)[1].strip() or None
    # Also check the (currently unused) error stash for older rows.
    err = req.error or ""
    if err.startswith("bap_issue_id="):
        return err.split("=", 1)[1].strip() or None
    return None


async def _emit_on_issue(
    db: AsyncSession,
    req: RefundRequest,
    *,
    action: str,
    short_desc: str,
    long_desc: str | None = None,
    bap_issue_id: str | None = None,
) -> None:
    """POST a Beckn /on_issue with the IGM resolution status to the BAP."""
    from app.beckn.callback_sender import (
        load_bpp_signing_key_b64,
        send_callback,
    )
    _proto_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "packages", "beckn-protocol")
    )
    if _proto_path not in sys.path:
        sys.path.insert(0, _proto_path)
    from python import build_on_issue_envelope

    order = await db.get(Order, req.order_id)
    if order is None:
        return
    bap_id = order.bap_id or settings.BELI_AMAN_BAP_ID
    bap_uri = settings.BELI_AMAN_BAP_URL

    envelope = build_on_issue_envelope(
        bap_id=bap_id,
        bap_uri=bap_uri,
        bpp_id=settings.BPP_SUBSCRIBER_ID,
        bpp_uri=settings.BPP_SUBSCRIBER_URL,
        transaction_id=str(order.id),
        issue_id=bap_issue_id or str(req.id),
        respondent_action=action,
        short_desc=short_desc,
        long_desc=long_desc or "",
        refund_amount=req.requested_amount if action == "RESOLVED" else None,
        refund_id=str(req.id) if action == "RESOLVED" else None,
        country_code=settings.BECKN_COUNTRY_CODE,
        city_code=settings.BECKN_CITY_CODE,
        core_version=settings.BECKN_CORE_VERSION,
    )

    try:
        await send_callback(
            bap_uri=bap_uri,
            action="on_issue",
            response_body=envelope,
            signing_private_key_b64=load_bpp_signing_key_b64(),
        )
    except Exception:
        logger.exception("emit /on_issue failed for refund %s", req.id)


async def _emit_refund_status(db: AsyncSession, req: RefundRequest, code: str) -> None:
    """POST a Beckn /on_update with the refund state change to the BAP."""
    from app.beckn.callback_sender import load_bpp_signing_key_b64, send_callback

    order = await db.get(Order, req.order_id)
    if order is None:
        return
    bap_id = order.bap_id or settings.BELI_AMAN_BAP_ID
    bap_uri = settings.BELI_AMAN_BAP_URL

    tag_list = [{"code": "refund_request_id", "value": str(req.id)}]
    if req.seller_note:
        tag_list.append({"code": "seller_note", "value": req.seller_note})
    if req.xendit_refund_id:
        tag_list.append({"code": "xendit_refund_id", "value": req.xendit_refund_id})

    body = {
        "context": {
            "domain": settings.BECKN_DOMAIN,
            "country": settings.BECKN_COUNTRY_CODE,
            "city": settings.BECKN_CITY_CODE,
            "action": "on_update",
            "core_version": settings.BECKN_CORE_VERSION,
            "bap_id": bap_id,
            "bap_uri": bap_uri,
            "bpp_id": settings.BPP_SUBSCRIBER_ID,
            "bpp_uri": settings.BPP_SUBSCRIBER_URL,
            "transaction_id": str(order.id),
            "message_id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        "message": {
            "order": {
                "id": order.beckn_order_id or str(order.id),
                "tags": [{"code": code, "list": tag_list}],
            }
        },
    }
    try:
        await send_callback(
            bap_uri=bap_uri, action="on_update",
            response_body=body,
            signing_private_key_b64=load_bpp_signing_key_b64(),
        )
    except Exception:
        logger.exception("emit refund status failed for %s", req.id)
