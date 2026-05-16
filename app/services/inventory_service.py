"""Race-safe inventory decrement for Beckn /confirm.

Uses Postgres SELECT ... FOR UPDATE row locks to ensure two concurrent
/confirms for the last unit can't both succeed.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sku import SKU

logger = logging.getLogger(__name__)


class OutOfStock(Exception):
    def __init__(self, sku_id, available: int, requested: int):
        super().__init__(f"sku {sku_id} short by {requested - available} (have {available})")
        self.sku_id = sku_id
        self.available = available
        self.requested = requested


@dataclass
class _LineRequest:
    sku_id: uuid.UUID
    qty: int


async def decrement_or_raise(db: AsyncSession, items: list[dict]) -> list[SKU]:
    """Decrement stock for each (sku_id, qty) pair atomically.

    Items is a list of dicts like [{"sku_id": "<uuid str>", "qty": 2}, ...].

    Acquires Postgres row locks via SELECT ... FOR UPDATE so concurrent calls
    cannot oversell. Raises OutOfStock on the first short line; the caller
    should rollback the transaction (this function does not commit).
    """
    lines = [_LineRequest(uuid.UUID(i["sku_id"]) if isinstance(i["sku_id"], str) else i["sku_id"], int(i["qty"])) for i in items]
    if not lines:
        return []

    sku_ids = [ln.sku_id for ln in lines]
    # Lock all relevant rows in one query
    locked = (
        await db.execute(
            select(SKU).where(SKU.id.in_(sku_ids)).with_for_update()
        )
    ).scalars().all()
    by_id = {s.id: s for s in locked}

    decremented: list[SKU] = []
    for ln in lines:
        sku = by_id.get(ln.sku_id)
        if sku is None:
            raise OutOfStock(ln.sku_id, 0, ln.qty)
        if sku.stock < ln.qty:
            raise OutOfStock(sku.id, sku.stock, ln.qty)
        sku.stock -= ln.qty
        decremented.append(sku)
    return decremented
