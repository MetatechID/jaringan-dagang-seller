"""Order lifecycle management with state machine validation."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.order import Order, OrderStatus


class InvalidOrderTransition(Exception):
    """Raised when an order state transition is not allowed."""

    def __init__(self, current: OrderStatus, target: OrderStatus) -> None:
        self.current = current
        self.target = target
        super().__init__(
            f"Cannot transition order from '{current.value}' to '{target.value}'"
        )


async def list_orders(
    db: AsyncSession,
    store_id: uuid.UUID,
    *,
    status: OrderStatus | None = None,
    offset: int = 0,
    limit: int = 50,
) -> Sequence[Order]:
    """List orders for a store with optional status filter."""
    stmt = (
        select(Order)
        .where(Order.store_id == store_id)
        .options(
            selectinload(Order.payment),
            selectinload(Order.fulfillment),
        )
        .offset(offset)
        .limit(limit)
        .order_by(Order.created_at.desc())
    )
    if status is not None:
        stmt = stmt.where(Order.status == status)

    result = await db.execute(stmt)
    return result.scalars().all()


async def get_order(
    db: AsyncSession,
    order_id: uuid.UUID,
) -> Order | None:
    """Fetch a single order with payment and fulfillment."""
    stmt = (
        select(Order)
        .where(Order.id == order_id)
        .options(
            selectinload(Order.payment),
            selectinload(Order.fulfillment),
        )
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_order_by_beckn_id(
    db: AsyncSession,
    beckn_order_id: str,
) -> Order | None:
    """Fetch an order by its Beckn order ID."""
    stmt = (
        select(Order)
        .where(Order.beckn_order_id == beckn_order_id)
        .options(
            selectinload(Order.payment),
            selectinload(Order.fulfillment),
        )
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_order(
    db: AsyncSession,
    store_id: uuid.UUID,
    data: dict[str, Any],
) -> Order:
    """Create a new order in CREATED state."""
    order = Order(
        store_id=store_id,
        beckn_order_id=data.get("beckn_order_id"),
        buyer_name=data.get("buyer_name"),
        buyer_phone=data.get("buyer_phone"),
        buyer_email=data.get("buyer_email"),
        billing_address=data.get("billing_address"),
        shipping_address=data.get("shipping_address"),
        status=OrderStatus.CREATED,
        total=Decimal(str(data.get("total", 0))),
        currency=data.get("currency", "IDR"),
        items=data.get("items"),
        payment_id=data.get("payment_id"),
        fulfillment_id=data.get("fulfillment_id"),
    )
    db.add(order)
    await db.flush()
    return order


async def update_order_status(
    db: AsyncSession,
    order_id: uuid.UUID,
    new_status: OrderStatus,
) -> Order:
    """Transition an order to a new status, enforcing valid transitions."""
    order = await get_order(db, order_id)
    if order is None:
        raise ValueError(f"Order {order_id} not found")

    if not order.can_transition_to(new_status):
        raise InvalidOrderTransition(order.status, new_status)

    order.status = new_status
    await db.flush()
    return order


async def cancel_order(
    db: AsyncSession,
    order_id: uuid.UUID,
) -> Order:
    """Cancel an order (validates that cancellation is allowed)."""
    return await update_order_status(db, order_id, OrderStatus.CANCELLED)
