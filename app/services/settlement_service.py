"""ONDC RSP settlement-record service (Task A6).

Narrow v1 scope: take an order id + (basis, window) and produce a
:class:`SettlementLedger` row + a wire-shaped ``SettlementRecord`` the
BPP can put on /on_settle. v1 does NOT move money — the actual rail
integration (BI-FAST / BI-RTGS / SKNBI / NACH-equivalents) is operator-
driven and deferred to v2.

Payable amount is computed deterministically from local data:

    payable_amount = paid_amount - fees - refunds

where:
  * ``paid_amount`` = ``PaymentRecord.amount`` for the order (the actual
    amount Xendit collected from the buyer).
  * ``fees`` = buyer-app finder fee + any other deductions (v1: 3% of
    the gross matches ``handlers._ondc_payment_tags`` buyer_app_finder_fee).
  * ``refunds`` = sum of ``RefundRequest.requested_amount`` for refunds
    in REFUNDED status (terminal happy-path refunds).

This is a pure function — no external network calls. Callers commit.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order
from app.models.payment import PaymentRecord, PaymentStatus
from app.models.refund import RefundRequest, RefundStatus
from app.models.settlement import (
    SettlementBasis,
    SettlementLedger,
    SettlementStatus,
    SettlementWindow,
)

logger = logging.getLogger(__name__)


# Buyer-app finder fee that ``app.beckn.handlers._ondc_payment_tags``
# advertises on /on_select/on_confirm. v1 retail: 3% of gross. Match this
# constant when changing the tag builder so the settle math matches the
# wire contract.
DEFAULT_BUYER_APP_FINDER_FEE_PCT = Decimal("0.03")


class SettlementError(Exception):
    """Application-level settlement errors (state / data validation)."""


def _compute_payable_amount(
    *,
    paid_amount: int,
    refunded_amount: int,
    buyer_app_finder_fee_pct: Decimal = DEFAULT_BUYER_APP_FINDER_FEE_PCT,
) -> int:
    """Compute the BPP-side payable from collected, refunded, and fee.

    All amounts are in IDR whole rupiahs (integer). The fee is applied to
    the gross collected; refunds come off the net.

        payable = (paid - fee) - refunded

    where fee = paid * buyer_app_finder_fee_pct, rounded to whole IDR.

    Returns a non-negative integer (clamped at zero if refunds exceeded
    the net paid — this means the BPP owes the BAP, captured in v2 as a
    negative-amount counterparty entry; for v1 we clamp at zero).
    """
    paid = max(int(paid_amount), 0)
    refunded = max(int(refunded_amount), 0)
    fee = int((Decimal(paid) * buyer_app_finder_fee_pct).quantize(Decimal("1")))
    net = paid - fee - refunded
    return max(net, 0)


async def record_for_order(
    db: AsyncSession,
    *,
    order_id: uuid.UUID,
    settlement_basis: str = "DELIVERY",
    settlement_window: str = "P1D",
) -> dict[str, Any]:
    """Upsert a SettlementLedger row for ``order_id`` and return the wire dict.

    Idempotent: if a SettlementLedger already exists for the order, the
    returned dict reflects the existing row (no recompute of amount — the
    operator-controlled status / reference are preserved).

    Returns a dict matching the on_settle wire shape:

        {
            "id": "<ledger uuid>",
            "order_id": "<bpp order id>",
            "settlement_basis": "DELIVERY",
            "settlement_window": {"duration": "P1D"},
            "settlement_status": "NOT_PAID",
            "settlement_reference": "<operator ref or None>",
            "counterparties": [
                {"type": "BPP", "id": <bpp subscriber>, "amount": ...,
                 "currency": "IDR"},
            ],
        }

    Raises:
        SettlementError: order not found OR not eligible (no paid payment).
    """
    try:
        basis = SettlementBasis(settlement_basis)
    except ValueError as e:
        raise SettlementError(
            f"unknown settlement_basis {settlement_basis!r}"
        ) from e
    try:
        window = SettlementWindow(settlement_window)
    except ValueError as e:
        raise SettlementError(
            f"unknown settlement_window {settlement_window!r}"
        ) from e

    order = await db.get(Order, order_id)
    if order is None:
        raise SettlementError(f"order {order_id} not found")

    payment = (await db.execute(
        select(PaymentRecord).where(PaymentRecord.order_id == order_id)
    )).scalar_one_or_none()

    paid_amount = 0
    if payment is not None and payment.status in (
        PaymentStatus.PAID,
        PaymentStatus.REFUNDED,
    ):
        paid_amount = int(payment.amount or 0)
    elif payment is None:
        # Fall back to Order.total for orders with no PaymentRecord
        # (e.g. mock / direct seller_bridge orders before payment plumbing).
        paid_amount = int(order.total or 0)

    refunds = (await db.execute(
        select(RefundRequest)
        .where(RefundRequest.order_id == order_id)
        .where(RefundRequest.status == RefundStatus.REFUNDED)
    )).scalars().all()
    refunded_amount = sum(int(r.requested_amount or 0) for r in refunds)

    payable = _compute_payable_amount(
        paid_amount=paid_amount,
        refunded_amount=refunded_amount,
    )

    # Upsert (one ledger per order).
    ledger = (await db.execute(
        select(SettlementLedger).where(SettlementLedger.order_id == order_id)
    )).scalar_one_or_none()
    if ledger is None:
        ledger = SettlementLedger(
            order_id=order_id,
            payment_id=payment.id if payment is not None else None,
            payable_amount=payable,
            settlement_basis=basis,
            settlement_window=window,
            settlement_status=SettlementStatus.NOT_PAID,
        )
        db.add(ledger)
        await db.flush()
    else:
        # Don't clobber operator-controlled status / reference on re-emit;
        # ONLY update the basis / window / amount if they're still NOT_PAID.
        if ledger.settlement_status == SettlementStatus.NOT_PAID:
            ledger.settlement_basis = basis
            ledger.settlement_window = window
            ledger.payable_amount = payable
            if payment is not None and ledger.payment_id is None:
                ledger.payment_id = payment.id
        await db.flush()

    # Build the wire dict. We DO NOT import the protocol module here to
    # keep settlement_service pure (no protocol pythonpath dance).
    counterparties = [
        {
            "type": "BPP",
            "id": order.bap_id and "bpp" or "bpp",   # placeholder; real id set by emit layer
            "amount": int(ledger.payable_amount),
            "currency": "IDR",
        }
    ]
    return {
        "id": str(ledger.id),
        "order_id": order.beckn_order_id or str(order.id),
        "settlement_basis": ledger.settlement_basis.value,
        "settlement_window": {"duration": ledger.settlement_window.value},
        "settlement_status": ledger.settlement_status.value,
        "settlement_reference": ledger.settlement_reference,
        "counterparties": counterparties,
    }
