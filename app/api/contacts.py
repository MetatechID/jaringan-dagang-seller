"""CRM contacts — read-only browse for the C3 dashboard (Task C2).

A ``Contact`` is one person the store has talked to over chat (bot or
agent). The bot bridge upserts these on every inbound message keyed on
``(store_id, external_id)``; this module is the read-side companion to
``app/api/conversations.py`` so the CRM list pane can render a customer's
identity + recent threads + their orders in one round-trip.

Note on order-join semantics: we link a contact to its orders by
``contact.email == orders.buyer_email``. Many chat contacts have no
email (anonymous web visitor), so ``orders`` will be empty for them —
that's expected, not a bug.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.conversations import _resolve_store_scope
from app.auth.deps import can_access_store, get_current_user
from app.database import get_db
from app.models.conversation import Contact, Conversation
from app.models.order import Order
from app.models.user import User

router = APIRouter(prefix="/contacts", tags=["contacts"])


_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200
_RECENT_CONV_LIMIT = 10
_RECENT_ORDER_LIMIT = 50


def _serialize_contact(c: Contact) -> dict[str, Any]:
    return {
        "id": str(c.id),
        "store_id": str(c.store_id),
        "external_id": c.external_id,
        "name": c.name,
        "email": c.email,
        "phone": c.phone,
        "avatar_url": c.avatar_url,
        "attributes": c.attributes,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


def _serialize_conv_summary(c: Conversation) -> dict[str, Any]:
    """A trimmed conversation shape for the contact-detail view.

    Same field set as the conversations endpoint's ``_serialize`` minus the
    join-noise fields (``contact_id`` — already known from context).
    """
    return {
        "id": str(c.id),
        "store_id": str(c.store_id),
        "inbox_id": str(c.inbox_id),
        "channel": c.channel.value if c.channel else None,
        "state": c.state.value if c.state else None,
        "last_message_at": (
            c.last_message_at.isoformat() if c.last_message_at else None
        ),
        "last_message_preview": c.last_message_preview,
        "unread_agent_count": int(c.unread_agent_count or 0),
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


def _serialize_order_summary(o: Order) -> dict[str, Any]:
    """Minimal order summary for the contact-detail view."""
    return {
        "id": str(o.id),
        "beckn_order_id": o.beckn_order_id,
        "status": o.status.value if o.status else None,
        "total": float(o.total) if o.total else 0,
        "currency": o.currency,
        "bap_id": getattr(o, "bap_id", None),
        "escrow_status": (
            o.escrow_status.value if getattr(o, "escrow_status", None) else "none"
        ),
        "created_at": o.created_at.isoformat() if o.created_at else None,
    }


@router.get("")
async def list_contacts(
    store_id: uuid.UUID | None = Query(default=None),
    q: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List contacts in the user's accessible stores.

    ``q`` does a case-insensitive substring match against name / email /
    phone. Super-admins may omit ``store_id`` to query across all stores;
    non-super-admins must pass an accessible ``store_id``.
    """
    effective_store_id = await _resolve_store_scope(db, user, store_id)

    stmt = select(Contact)
    if effective_store_id is not None:
        stmt = stmt.where(Contact.store_id == effective_store_id)
    if q:
        pat = f"%{q}%"
        stmt = stmt.where(
            or_(
                Contact.name.ilike(pat),
                Contact.email.ilike(pat),
                Contact.phone.ilike(pat),
            )
        )
    stmt = (
        stmt.order_by(Contact.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return {"data": [_serialize_contact(c) for c in rows]}


@router.get("/{contact_id}")
async def get_contact(
    contact_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Customer 360 — contact identity + recent conversations + orders.

    Orders are joined by ``contact.email == orders.buyer_email``. Anonymous
    contacts (no email) come back with an empty ``orders`` list. The store
    scope is enforced via the contact's ``store_id``; we never join across
    stores.

    Returns 404 both when the row is absent AND when the caller has no
    access to its store — same response in both cases so we don't leak
    existence.
    """
    contact = (
        await db.execute(select(Contact).where(Contact.id == contact_id))
    ).scalar_one_or_none()
    if contact is None:
        raise HTTPException(404, "contact not found")
    if not user.is_super_admin:
        if not await can_access_store(db, user, contact.store_id):
            raise HTTPException(404, "contact not found")

    convs = (
        await db.execute(
            select(Conversation)
            .where(Conversation.contact_id == contact.id)
            .order_by(Conversation.last_message_at.desc().nulls_last())
            .limit(_RECENT_CONV_LIMIT)
        )
    ).scalars().all()

    orders: list[Order] = []
    if contact.email:
        orders = (
            await db.execute(
                select(Order)
                .where(Order.store_id == contact.store_id)
                .where(Order.buyer_email == contact.email)
                .order_by(Order.created_at.desc())
                .limit(_RECENT_ORDER_LIMIT)
            )
        ).scalars().all()

    return {
        "data": {
            **_serialize_contact(contact),
            "conversations": [_serialize_conv_summary(c) for c in convs],
            "orders": [_serialize_order_summary(o) for o in orders],
        }
    }
