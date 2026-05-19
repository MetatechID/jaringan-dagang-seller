"""CRM inboxes — list + create (Task C2).

An ``Inbox`` is a channel surface (web widget, WA business number, …)
that conversations live in. The C3 dashboard filters the conversation list
by inbox; the bridge looks up an inbox by store to attach a new
conversation to.

Create is store-owner-only (or super-admin) because adding an inbox
re-wires which channels the store is reachable on — a config change, not
a daily operation.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.conversations import _resolve_store_scope
from app.auth.deps import can_access_store, get_current_user
from app.database import get_db
from app.models.conversation import Channel, Inbox
from app.models.store_membership import StoreRole
from app.models.user import User

router = APIRouter(prefix="/inboxes", tags=["inboxes"])


class CreateInboxBody(BaseModel):
    store_id: uuid.UUID
    name: str
    channel: Channel
    config: dict[str, Any] | None = None


def _serialize_inbox(i: Inbox) -> dict[str, Any]:
    return {
        "id": str(i.id),
        "store_id": str(i.store_id),
        "name": i.name,
        "channel": i.channel.value if i.channel else None,
        "config": i.config,
        "created_at": i.created_at.isoformat() if i.created_at else None,
        "updated_at": i.updated_at.isoformat() if i.updated_at else None,
    }


@router.get("")
async def list_inboxes(
    store_id: uuid.UUID | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List inboxes scoped to the user's stores.

    Super-admins may omit ``store_id``; non-super-admins must pass an
    accessible one. Returns in stable name order so C3's filter dropdown
    has a deterministic UI.
    """
    effective_store_id = await _resolve_store_scope(db, user, store_id)

    stmt = select(Inbox)
    if effective_store_id is not None:
        stmt = stmt.where(Inbox.store_id == effective_store_id)
    stmt = stmt.order_by(Inbox.name)
    rows = (await db.execute(stmt)).scalars().all()
    return {"data": [_serialize_inbox(i) for i in rows]}


@router.post("", status_code=201)
async def create_inbox(
    body: CreateInboxBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Create a new inbox for a store. Owner-only (or super-admin).

    Channel-specific config (e.g. WA ``phone_number_id``, widget id, allowed
    origins) lives in the JSONB ``config`` field — the schema is
    intentionally generic; per-channel validation is the bridge's job.
    """
    if not user.is_super_admin:
        if not await can_access_store(
            db, user, body.store_id, min_role=StoreRole.OWNER
        ):
            raise HTTPException(403, "store owner only")

    inbox = Inbox(
        store_id=body.store_id,
        name=body.name,
        channel=body.channel,
        config=body.config,
    )
    db.add(inbox)
    await db.flush()
    await db.refresh(inbox)
    return {"data": _serialize_inbox(inbox)}
