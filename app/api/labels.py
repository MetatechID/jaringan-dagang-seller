"""CRM labels — list + create (Task C2).

Labels are coloured tags an agent can apply to conversations
(e.g. ``refund``, ``vip``). Schema enforces unique ``(store_id, name)`` per
store, so the same label name can exist in different stores without
collision.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.conversations import _resolve_store_scope
from app.auth.deps import can_access_store, get_current_user
from app.database import get_db
from app.models.conversation import Label
from app.models.user import User

router = APIRouter(prefix="/labels", tags=["labels"])


class CreateLabelBody(BaseModel):
    store_id: uuid.UUID
    name: str
    color: str | None = None


def _serialize_label(l: Label) -> dict[str, Any]:
    return {
        "id": str(l.id),
        "store_id": str(l.store_id),
        "name": l.name,
        "color": l.color,
        "created_at": l.created_at.isoformat() if l.created_at else None,
        "updated_at": l.updated_at.isoformat() if l.updated_at else None,
    }


@router.get("")
async def list_labels(
    store_id: uuid.UUID | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List labels for the user's accessible stores.

    Super-admins may omit ``store_id``; non-super-admins must pass an
    accessible one. Sorted by name so C3's filter dropdown is stable.
    """
    effective_store_id = await _resolve_store_scope(db, user, store_id)

    stmt = select(Label)
    if effective_store_id is not None:
        stmt = stmt.where(Label.store_id == effective_store_id)
    stmt = stmt.order_by(Label.name)
    rows = (await db.execute(stmt)).scalars().all()
    return {"data": [_serialize_label(l) for l in rows]}


@router.post("", status_code=201)
async def create_label(
    body: CreateLabelBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Create a label. Any user with store access (not just owner) — labels
    are operational, not configuration.

    The schema's unique index on ``(store_id, name)`` is enforced server-side
    on collision we return 409 rather than the raw IntegrityError.
    """
    if not user.is_super_admin:
        if not await can_access_store(db, user, body.store_id):
            raise HTTPException(403, "no access to this store")

    label = Label(
        store_id=body.store_id,
        name=body.name,
        color=body.color,
    )
    db.add(label)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "label with this name already exists in this store")
    await db.refresh(label)
    return {"data": _serialize_label(label)}
