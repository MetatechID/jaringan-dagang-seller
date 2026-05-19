"""Chatwoot-style CRM models — contacts, inboxes, conversations, messages,
labels (Task C1).

Why this schema exists
----------------------
A nullclaw chatbot at ``safiya.beliaman.com/chat`` (built later in B4/B5)
plus a Chatwoot-style 3-pane CRM dashboard (built later in C2/C3) need a
common store-scoped tabular shape so agents can take human handoff on a
bot thread. Today there are no chat tables; this module is the single
greenfield commit that creates them.

Bot↔CRM contract (enforced by C2/C4, supported by this schema)
--------------------------------------------------------------
* The bridge writes ``contacts`` / ``inboxes`` / ``conversations`` /
  ``messages`` (``sender in (contact, bot)``, ``delivery='na'``), maintains
  ``conversation.last_message_at``, defaults ``state='bot_active'``. Before
  replying, it READS ``conversation.state`` and stays silent if
  ``state='human_handoff'``.
* The CRM writes agent messages (``sender='agent'``, ``delivery='pending'``);
  the bridge polls pending agent messages, delivers via the channel, sets
  ``delivery='sent'`` / ``'failed'``. The handoff state flip is atomic with
  the first agent-message insert.
* Idempotency: bridge supplies ``external_id`` on contacts / conversations /
  messages. Partial unique indexes on those tuples make replay a no-op.

Multi-tenant
------------
Every row is ``store_id``-scoped — v1 is just Safiya but the schema must
support N stores cleanly. ``Message`` carries a denormalized ``store_id`` so
the CRM can run store-scoped queries without a join through ``conversations``.

Channels
--------
``conv_channel`` enum starts at ``website``; ``whatsapp`` is in the type so
WhatsApp onboarding (later phase) needs zero schema migration.

Conventions
-----------
* ``UUIDPrimaryKeyMixin``, ``TimestampMixin``, ``Base`` from
  ``app/models/base.py`` (matches ``order.py`` / ``refund.py``).
* ``SAEnum(..., name="…")`` Postgres-side type name pinned for stability.
* ``JSONB`` for structured content; we do NOT enforce a JSON Schema on
  ``Message.content`` — the contract (``{text, blocks?}``) is C2's
  responsibility.
* All FK constraints are ``ondelete='CASCADE'`` except ``assignee_user_id``
  and ``sender_user_id``, which are ``ondelete='SET NULL'`` (deleting an
  agent must not nuke their conversations / messages).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Column,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Channel(str, enum.Enum):
    """The transport / surface a conversation lives on.

    Postgres type name: ``conv_channel``.
    """

    WEBSITE = "website"
    WHATSAPP = "whatsapp"


class ConversationState(str, enum.Enum):
    """High-level lifecycle of a conversation.

    * ``bot_active`` — bot is autonomously replying.
    * ``human_handoff`` — agent has taken over; bridge stays silent until
      flipped back (or to ``resolved``). The flip is atomic with the first
      agent-message insert (C2).
    * ``resolved`` — closed by an agent; new buyer message reopens.

    Postgres type name: ``conversation_state``.
    """

    BOT_ACTIVE = "bot_active"
    HUMAN_HANDOFF = "human_handoff"
    RESOLVED = "resolved"


class MessageSender(str, enum.Enum):
    """Who authored a message.

    ``sender_user_id`` is only populated when ``sender == 'agent'``.

    Postgres type name: ``message_sender``.
    """

    CONTACT = "contact"
    BOT = "bot"
    AGENT = "agent"


class MessageDelivery(str, enum.Enum):
    """Delivery state of a message to the customer.

    * ``na`` — inbound (contact-sent) or bot reply: delivery is irrelevant
      because the bot speaks via the same channel synchronously.
    * ``pending`` — agent message awaiting bridge pickup.
    * ``sent`` — bridge delivered it to the channel.
    * ``failed`` — bridge tried and the channel returned an error; retry is
      a C4 concern.

    Postgres type name: ``message_delivery``.
    """

    NA = "na"
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


# Shared SAEnum instances. Reusing the same instance across columns means
# Postgres emits a single ``CREATE TYPE conv_channel AS ENUM (…)`` instead of
# trying (and failing) to create the same type twice. Both ``Inbox.channel``
# and ``Conversation.channel`` point at this single instance.
#
# ``values_callable=lambda x: [e.value for e in x]`` makes Postgres store the
# enum VALUES (lowercase ``website`` / ``whatsapp`` / …) instead of the NAMES
# (uppercase ``WEBSITE`` / ``WHATSAPP``). The bot↔CRM JSON contract carries
# lowercase strings (e.g. ``{"channel": "website"}``), so the Postgres-side
# representation matches the wire one. This mirrors ``order.escrow_status``.
_values = lambda x: [e.value for e in x]  # noqa: E731

_CHANNEL_SAENUM = SAEnum(
    Channel,
    name="conv_channel",
    create_constraint=True,
    values_callable=_values,
)
_STATE_SAENUM = SAEnum(
    ConversationState,
    name="conversation_state",
    create_constraint=True,
    values_callable=_values,
)
_SENDER_SAENUM = SAEnum(
    MessageSender,
    name="message_sender",
    create_constraint=True,
    values_callable=_values,
)
_DELIVERY_SAENUM = SAEnum(
    MessageDelivery,
    name="message_delivery",
    create_constraint=True,
    values_callable=_values,
)


# ---------------------------------------------------------------------------
# Contact — a buyer (or anonymous web visitor) the store has talked to.
# ---------------------------------------------------------------------------


class Contact(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A person the store has interacted with, scoped to one store.

    ``external_id`` is the bridge's stable id (WhatsApp phone, website
    session id, …). The partial unique index on ``(store_id, external_id)``
    where ``external_id IS NOT NULL`` makes bridge replay idempotent.
    Rows with no ``external_id`` are agent-created (e.g. an agent adding a
    walk-in customer manually) and are not deduped.
    """

    __tablename__ = "contacts"

    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stores.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    external_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    attributes: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"<Contact(id={self.id}, store={self.store_id}, "
            f"name={self.name!r}, external_id={self.external_id!r})>"
        )


# Partial unique index for bridge idempotency. Bridge supplies
# ``external_id`` on every write; rows without one (manual creates) are
# not constrained. Postgres only — sqlite ignores ``postgresql_where``.
Index(
    "uq_contacts_store_external_id",
    Contact.store_id,
    Contact.external_id,
    unique=True,
    postgresql_where=Contact.external_id.isnot(None),
)


# ---------------------------------------------------------------------------
# Inbox — a channel surface, e.g. "Safiya website chat" or "WA business
# +62...". One conversation lives in exactly one inbox.
# ---------------------------------------------------------------------------


class Inbox(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A channel surface (web widget, WA business number, …) owned by a store.

    ``config`` is a flexible JSONB for channel-specific knobs (e.g. WA
    ``phone_number_id``, website widget id, allowed origins). C2 codifies
    the per-channel shape; the schema is intentionally schema-less here.
    """

    __tablename__ = "inboxes"

    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stores.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    channel: Mapped[Channel] = mapped_column(_CHANNEL_SAENUM, nullable=False)
    config: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<Inbox(id={self.id}, store={self.store_id}, "
            f"name={self.name!r}, channel={self.channel.value})>"
        )


# ---------------------------------------------------------------------------
# Conversation — a thread of messages between one Contact and one Inbox.
# ---------------------------------------------------------------------------


class Conversation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A thread between a Contact and an Inbox.

    Sort key for the CRM inbox list is ``last_message_at`` — kept fresh by
    the bridge on every inbound message and by the CRM on every agent
    message. ``last_message_preview`` is a denormalized ≤280-char snippet
    so the list pane can render without joining messages.

    State machine (enforced by C2):

        bot_active ──agent reply──> human_handoff ──"resolve"──> resolved
                                                       │
                                                       └──new buyer msg──> human_handoff
    """

    __tablename__ = "conversations"

    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stores.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    inbox_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("inboxes.id", ondelete="CASCADE"),
        nullable=False,
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
    )
    channel: Mapped[Channel] = mapped_column(_CHANNEL_SAENUM, nullable=False)
    state: Mapped[ConversationState] = mapped_column(
        _STATE_SAENUM,
        nullable=False,
        default=ConversationState.BOT_ACTIVE,
        index=True,
    )
    external_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    last_message_preview: Mapped[str | None] = mapped_column(
        String(280), nullable=True
    )
    unread_agent_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    handoff_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"<Conversation(id={self.id}, store={self.store_id}, "
            f"state={self.state.value}, channel={self.channel.value})>"
        )


# Bridge idempotency: same (store, external_id) is a single conversation.
Index(
    "uq_conversations_store_external_id",
    Conversation.store_id,
    Conversation.external_id,
    unique=True,
    postgresql_where=Conversation.external_id.isnot(None),
)


# ---------------------------------------------------------------------------
# Message — one utterance in a conversation.
# ---------------------------------------------------------------------------


class Message(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One message in a conversation.

    ``content`` is a JSONB blob shaped like::

        {"text": "Hello!",
         "blocks": [
             {"type": "product_card", "product_id": "…", …},
             {"type": "image", "url": "…"},
             {"type": "qr", "data": "…"},
         ]}

    The shape is **not** enforced at the DB layer (we use plain JSONB).
    C2 owns the contract; the schema stays generic so we can add block
    types without migrating.

    ``store_id`` is denormalized off ``conversation.store_id`` so the CRM
    can run store-scoped queries (``WHERE store_id = :sid AND delivery =
    'pending'``) without joining through conversations.
    """

    __tablename__ = "messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stores.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sender: Mapped[MessageSender] = mapped_column(
        _SENDER_SAENUM, nullable=False
    )
    sender_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    external_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    delivery: Mapped[MessageDelivery] = mapped_column(
        _DELIVERY_SAENUM,
        nullable=False,
        default=MessageDelivery.NA,
        index=True,
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"<Message(id={self.id}, conv={self.conversation_id}, "
            f"sender={self.sender.value}, delivery={self.delivery.value})>"
        )


# Bridge idempotency: same (conversation, external_id) is a single message.
Index(
    "uq_messages_conv_external_id",
    Message.conversation_id,
    Message.external_id,
    unique=True,
    postgresql_where=Message.external_id.isnot(None),
)


# ---------------------------------------------------------------------------
# Label — a tag agents can apply to conversations (e.g. "refund", "VIP").
# ---------------------------------------------------------------------------


class Label(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A coloured tag scoped to one store.

    Labels are many-to-many with conversations via the
    ``conversation_labels`` join table.
    """

    __tablename__ = "labels"

    store_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stores.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    color: Mapped[str | None] = mapped_column(String(16), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<Label(id={self.id}, store={self.store_id}, name={self.name!r})>"
        )


Index("uq_labels_store_name", Label.store_id, Label.name, unique=True)


# ---------------------------------------------------------------------------
# Conversation ↔ Label join table.
#
# Plain ``Table(...)`` (no ORM class) keeps it lightweight; C2 will pass it
# to ``secondary=`` on a relationship if useful, but most CRM filters work
# off a direct ``SELECT … FROM conversation_labels WHERE label_id IN …``.
# Both FKs cascade so deleting a Label or a Conversation cleans up the
# association rows.
# ---------------------------------------------------------------------------


conversation_labels = Table(
    "conversation_labels",
    Base.metadata,
    Column(
        "conversation_id",
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "label_id",
        UUID(as_uuid=True),
        ForeignKey("labels.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)
