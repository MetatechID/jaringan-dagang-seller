"""Chatwoot-style CRM — conversation routes (Task C2).

This module is the CRM-write side of the bot↔CRM contract enforced by the
schema in ``app/models/conversation.py``:

* The bot bridge (B4, later) writes ``contacts`` / ``inboxes`` / ``conversations``
  / ``messages`` (``sender in (contact, bot)``, ``delivery='na'``) and maintains
  ``conversation.last_message_at`` / ``unread_agent_count``. Before replying it
  READS ``conversation.state`` and stays silent if ``state='human_handoff'``.
* This module owns the CRM-write side: agents take over threads, send messages
  (``sender='agent', delivery='pending'``), resolve / reopen / assign, and apply
  labels.
* **The headline atomicity contract**: ``POST /messages`` MUST commit the
  agent-message INSERT and the ``state→human_handoff`` UPDATE in one
  transaction. If those landed separately, the bridge could observe
  ``state=bot_active`` and still send a bot reply that races the human.

Auth model
----------
Reused verbatim from ``app/auth/deps.py``:

* ``Depends(get_current_user)`` materializes the User from a Firebase ID
  token; auto-promotes super-admins on first sign-in.
* ``can_access_store(db, user, store_id)`` is the single ACL chokepoint.
  Super-admins (``user.is_super_admin``) pass automatically.
* Non-super-admins MUST pass ``store_id`` (400 if missing) and have a
  ``StoreMembership`` for it (403 otherwise).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import and_, delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import can_access_store, get_current_user
from app.database import get_db
from app.models.conversation import (
    Conversation,
    ConversationState,
    Inbox,
    Label,
    Message,
    MessageDelivery,
    MessageSender,
    conversation_labels,
)
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/conversations", tags=["conversations"])


# Preview length the CRM list pane renders. Schema column is String(280); we
# truncate writer-side so the column never reaches its hard ceiling on a
# Postgres reject. C3's UI doesn't need anything longer.
_PREVIEW_MAX = 280
_DEFAULT_LIST_LIMIT = 50
_MAX_LIST_LIMIT = 200
_DEFAULT_MSG_LIMIT = 100
_MAX_MSG_LIMIT = 500


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class MessageContent(BaseModel):
    """Wire shape of an agent-authored message body.

    The schema stays generic (plain JSONB on the column) so future block types
    (e.g. ``product_card``, ``image``, ``qr``) don't need a migration.
    """

    text: str
    blocks: list[dict[str, Any]] | None = None


class PostMessageBody(BaseModel):
    content: MessageContent


class AssignBody(BaseModel):
    assignee_user_id: uuid.UUID


class AttachLabelBody(BaseModel):
    label_id: uuid.UUID


# ---------------------------------------------------------------------------
# ACL helpers
# ---------------------------------------------------------------------------


async def _resolve_store_scope(
    db: AsyncSession,
    user: User,
    store_id: uuid.UUID | None,
) -> uuid.UUID | None:
    """Return the store_id to scope the query by, or ``None`` for super-admin
    listing across all stores.

    * Super-admin without ``store_id`` → returns ``None`` (caller does NOT
      filter by store).
    * Super-admin with ``store_id`` → returns it (filter to that store only).
    * Non-super-admin without ``store_id`` → 400.
    * Non-super-admin with inaccessible ``store_id`` → 403.
    """
    if user.is_super_admin:
        return store_id  # may be None → no scope filter

    if store_id is None:
        raise HTTPException(
            400, "store_id is required for non-super-admin users"
        )
    if not await can_access_store(db, user, store_id):
        raise HTTPException(403, "no access to this store")
    return store_id


async def _load_conversation_for_user(
    db: AsyncSession,
    user: User,
    conversation_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> Conversation:
    """Fetch a conversation, applying the user's ACL.

    Returns the row only if the user can access its store. Otherwise raises
    HTTPException(404) — we never leak existence to unauthorised users.

    ``for_update`` adds ``FOR UPDATE`` so the row is row-locked for the duration
    of the calling transaction (used by the agent-message handoff path).
    """
    stmt = select(Conversation).where(Conversation.id == conversation_id)
    if for_update:
        stmt = stmt.with_for_update()
    conv = (await db.execute(stmt)).scalar_one_or_none()
    if conv is None:
        raise HTTPException(404, "conversation not found")
    if not user.is_super_admin:
        if not await can_access_store(db, user, conv.store_id):
            # Same 404 we'd return for a missing row — don't leak existence.
            raise HTTPException(404, "conversation not found")
    return conv


def _truncate_preview(text: str | None) -> str | None:
    """Truncate a message's text for the conversation list pane.

    The schema column is ``String(280)``; this helper enforces the limit
    writer-side so an over-long message body can't trip a Postgres length
    constraint at insert time. C3's UI assumes ``≤ 280`` and doesn't render
    longer.
    """
    if text is None:
        return None
    if len(text) <= _PREVIEW_MAX:
        return text
    return text[:_PREVIEW_MAX]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def _serialize_conversation(c: Conversation) -> dict[str, Any]:
    return {
        "id": str(c.id),
        "store_id": str(c.store_id),
        "inbox_id": str(c.inbox_id),
        "contact_id": str(c.contact_id),
        "channel": c.channel.value if c.channel else None,
        "state": c.state.value if c.state else None,
        "external_id": c.external_id,
        "assignee_user_id": (
            str(c.assignee_user_id) if c.assignee_user_id else None
        ),
        "last_message_at": (
            c.last_message_at.isoformat() if c.last_message_at else None
        ),
        "last_message_preview": c.last_message_preview,
        "unread_agent_count": int(c.unread_agent_count or 0),
        "handoff_at": c.handoff_at.isoformat() if c.handoff_at else None,
        "resolved_at": c.resolved_at.isoformat() if c.resolved_at else None,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


def _serialize_message(m: Message) -> dict[str, Any]:
    return {
        "id": str(m.id),
        "conversation_id": str(m.conversation_id),
        "store_id": str(m.store_id),
        "sender": m.sender.value if m.sender else None,
        "sender_user_id": (
            str(m.sender_user_id) if m.sender_user_id else None
        ),
        "content": m.content,
        "external_id": m.external_id,
        "delivery": m.delivery.value if m.delivery else None,
        "delivered_at": (
            m.delivered_at.isoformat() if m.delivered_at else None
        ),
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
    }


# ---------------------------------------------------------------------------
# List + get conversations
# ---------------------------------------------------------------------------


@router.get("")
async def list_conversations(
    store_id: uuid.UUID | None = Query(default=None),
    state: ConversationState | None = Query(default=None),
    assignee_user_id: uuid.UUID | None = Query(default=None),
    inbox_id: uuid.UUID | None = Query(default=None),
    label_id: uuid.UUID | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=_DEFAULT_LIST_LIMIT, ge=1, le=_MAX_LIST_LIMIT),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List conversations matching the filter set.

    Super-admins MAY omit ``store_id`` to query across all stores.
    Non-super-admins MUST pass ``store_id`` (400 otherwise) and have access
    to it (403 otherwise).

    Sort is ``last_message_at DESC, created_at DESC`` — the CRM list pane's
    natural ordering. Default page is 50; max 200.
    """
    effective_store_id = await _resolve_store_scope(db, user, store_id)

    stmt = select(Conversation)
    if effective_store_id is not None:
        stmt = stmt.where(Conversation.store_id == effective_store_id)
    if state is not None:
        stmt = stmt.where(Conversation.state == state)
    if assignee_user_id is not None:
        stmt = stmt.where(Conversation.assignee_user_id == assignee_user_id)
    if inbox_id is not None:
        stmt = stmt.where(Conversation.inbox_id == inbox_id)
    if label_id is not None:
        # Join through conversation_labels — no ORM relationship needed.
        stmt = stmt.join(
            conversation_labels,
            conversation_labels.c.conversation_id == Conversation.id,
        ).where(conversation_labels.c.label_id == label_id)

    stmt = (
        stmt.order_by(
            Conversation.last_message_at.desc().nulls_last(),
            Conversation.created_at.desc(),
        )
        .offset(offset)
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return {"data": [_serialize_conversation(c) for c in rows]}


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Fetch a single conversation, scope-checked.

    Returns 404 both when the row is absent AND when the caller has no access
    to its store — same response in both cases so we don't leak existence.
    """
    conv = await _load_conversation_for_user(db, user, conversation_id)
    return {"data": _serialize_conversation(conv)}


# ---------------------------------------------------------------------------
# Messages: list + post
# ---------------------------------------------------------------------------


@router.get("/{conversation_id}/messages")
async def list_messages(
    conversation_id: uuid.UUID,
    after_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=_DEFAULT_MSG_LIMIT, ge=1, le=_MAX_MSG_LIMIT),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List messages in a conversation, oldest-first.

    Ordering: ``(created_at ASC, id ASC)``. ``after_id`` returns only messages
    strictly after the given message's ``(created_at, id)`` — same compound
    key as the ORDER BY so cursor pagination stays stable when many rows
    share a microsecond.

    A bad ``after_id`` (no such message) returns 400. An inaccessible
    conversation returns 404.
    """
    conv = await _load_conversation_for_user(db, user, conversation_id)

    stmt = select(Message).where(Message.conversation_id == conv.id)

    if after_id is not None:
        anchor = (
            await db.execute(select(Message).where(Message.id == after_id))
        ).scalar_one_or_none()
        if anchor is None or anchor.conversation_id != conv.id:
            raise HTTPException(400, "after_id does not belong to this conversation")
        # ``(created_at, id)`` is the order; ``after`` is strictly greater.
        stmt = stmt.where(
            (Message.created_at > anchor.created_at)
            | and_(
                Message.created_at == anchor.created_at,
                Message.id > anchor.id,
            )
        )

    stmt = stmt.order_by(Message.created_at.asc(), Message.id.asc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return {"data": [_serialize_message(m) for m in rows]}


@router.post("/{conversation_id}/messages", status_code=201)
async def post_agent_message(
    conversation_id: uuid.UUID,
    body: PostMessageBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Insert an agent-authored message and (if needed) flip the conversation
    to ``human_handoff`` in a single transaction.

    The atomic contract (locked in by C2, relied on by B4 bridge):
      1. ``SELECT ... FOR UPDATE`` the conversation row to serialise
         concurrent agents.
      2. INSERT ``Message(sender=agent, sender_user_id=user.id,
         delivery=pending, content=<json>)``.
      3. UPDATE the conversation: ``last_message_at=now()``,
         ``last_message_preview=<truncated 280>``, ``unread_agent_count=0``.
         If ``state=bot_active``: also ``state=human_handoff,
         handoff_at=now(), assignee_user_id=user.id``.
      4. The session is committed by ``get_db()`` on successful return; any
         exception triggers ``get_db()``'s rollback so both the INSERT and
         UPDATE roll back together.

    A ``resolved`` conversation rejects with 409 — agents must reopen first.
    This protects the state machine: bot won't reply on a resolved thread,
    and silently un-resolving it because someone sent a message would
    surprise the agent who closed it.
    """
    # FOR UPDATE so two parallel agents replying race-safely.
    conv = await _load_conversation_for_user(
        db, user, conversation_id, for_update=True
    )

    if conv.state == ConversationState.RESOLVED:
        raise HTTPException(
            409, "Resolved; use /reopen first"
        )

    now = _utcnow()
    text = body.content.text or ""

    # 1) Insert the message. We build the model and add() it; flush() drives
    #    the INSERT but stays in the open transaction.
    msg = Message(
        conversation_id=conv.id,
        store_id=conv.store_id,
        sender=MessageSender.AGENT,
        sender_user_id=user.id,
        content=body.content.model_dump(exclude_none=True),
        delivery=MessageDelivery.PENDING,
    )
    db.add(msg)

    # 2) Update conversation in the same transaction. If the bridge polls
    #    between INSERT and UPDATE, transaction isolation hides both writes
    #    until commit. The FOR UPDATE lock guarantees a parallel agent can't
    #    interleave a state read+write here.
    conv.last_message_at = now
    conv.last_message_preview = _truncate_preview(text)
    conv.unread_agent_count = 0
    if conv.state == ConversationState.BOT_ACTIVE:
        conv.state = ConversationState.HUMAN_HANDOFF
        conv.handoff_at = now
        conv.assignee_user_id = user.id

    await db.flush()
    # get_db() will commit on successful return. We do NOT call commit() here
    # so a downstream exception still rolls both writes back together.
    await db.refresh(msg)
    return {"data": _serialize_message(msg)}


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------


@router.post("/{conversation_id}/take-over")
async def take_over(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Take human ownership of a conversation.

    * ``bot_active`` → ``human_handoff`` (assign self, stamp ``handoff_at``).
    * ``human_handoff`` → idempotent (return current row, no changes).
    * ``resolved`` → 409 (use /reopen first).
    """
    conv = await _load_conversation_for_user(
        db, user, conversation_id, for_update=True
    )
    if conv.state == ConversationState.RESOLVED:
        raise HTTPException(409, "Resolved; use /reopen first")

    if conv.state != ConversationState.HUMAN_HANDOFF:
        conv.state = ConversationState.HUMAN_HANDOFF
        conv.handoff_at = _utcnow()
        conv.assignee_user_id = user.id
        await db.flush()
    return {"data": _serialize_conversation(conv)}


@router.post("/{conversation_id}/assign")
async def assign(
    conversation_id: uuid.UUID,
    body: AssignBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Reassign the conversation to another user.

    The target user must have store access (super-admin or membership).
    Refused with 403 if they don't — assignment isn't a back-door past the
    ACL.

    No state change: assignment is orthogonal to ``state``. Use ``/take-over``
    to flip to ``human_handoff``.
    """
    conv = await _load_conversation_for_user(
        db, user, conversation_id, for_update=True
    )

    # Resolve target user.
    target = (
        await db.execute(select(User).where(User.id == body.assignee_user_id))
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(404, "target user not found")

    # Target must be able to access this store. Super-admin always can.
    if not target.is_super_admin:
        if not await can_access_store(db, target, conv.store_id):
            raise HTTPException(
                403, "target user has no access to this store"
            )

    conv.assignee_user_id = target.id
    await db.flush()
    return {"data": _serialize_conversation(conv)}


@router.post("/{conversation_id}/resolve")
async def resolve(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Close the conversation.

    ``state=resolved``, ``resolved_at=now()``, ``assignee_user_id=NULL``.
    Idempotent: if already ``resolved``, return current row unchanged.
    """
    conv = await _load_conversation_for_user(
        db, user, conversation_id, for_update=True
    )
    if conv.state != ConversationState.RESOLVED:
        conv.state = ConversationState.RESOLVED
        conv.resolved_at = _utcnow()
        conv.assignee_user_id = None
        await db.flush()
    return {"data": _serialize_conversation(conv)}


@router.post("/{conversation_id}/reopen")
async def reopen(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Reopen a resolved conversation back to ``bot_active``.

    Clears ``resolved_at`` only — leaves ``handoff_at`` / ``assignee_user_id``
    intact for audit (which agent had it last). The bridge will start
    replying again because ``state=bot_active``.
    """
    conv = await _load_conversation_for_user(
        db, user, conversation_id, for_update=True
    )
    if conv.state != ConversationState.BOT_ACTIVE:
        conv.state = ConversationState.BOT_ACTIVE
        conv.resolved_at = None
        await db.flush()
    return {"data": _serialize_conversation(conv)}


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------


@router.post("/{conversation_id}/labels", status_code=201)
async def attach_label(
    conversation_id: uuid.UUID,
    body: AttachLabelBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Attach a label to a conversation.

    Rejects cross-store labels (404). Idempotent: re-attaching the same label
    returns ``200`` with ``{"data": {"attached": false}}`` instead of 201.
    Uses Postgres ``INSERT ... ON CONFLICT DO NOTHING`` so two parallel
    attachers don't both 500.
    """
    conv = await _load_conversation_for_user(
        db, user, conversation_id
    )

    label = (
        await db.execute(select(Label).where(Label.id == body.label_id))
    ).scalar_one_or_none()
    if label is None:
        raise HTTPException(404, "label not found")
    if label.store_id != conv.store_id:
        # Don't leak that the label exists in another store.
        raise HTTPException(404, "label not found")

    stmt = (
        pg_insert(conversation_labels)
        .values(conversation_id=conv.id, label_id=label.id)
        .on_conflict_do_nothing()
    )
    await db.execute(stmt)
    await db.flush()
    return {
        "data": {
            "conversation_id": str(conv.id),
            "label_id": str(label.id),
        }
    }


@router.delete(
    "/{conversation_id}/labels/{label_id}", status_code=204
)
async def detach_label(
    conversation_id: uuid.UUID,
    label_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Detach a label from a conversation. 204 either way (idempotent)."""
    conv = await _load_conversation_for_user(
        db, user, conversation_id
    )
    stmt = delete(conversation_labels).where(
        conversation_labels.c.conversation_id == conv.id,
        conversation_labels.c.label_id == label_id,
    )
    await db.execute(stmt)
    await db.flush()
    return Response(status_code=204)
