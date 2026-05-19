"""Task C1 — Chatwoot-style CRM schema (greenfield).

These tests pin the shape of ``app/models/conversation.py``: enums, model
classes, columns, FK targets / ondelete behaviour, defaults, and the unique
partial indexes that enforce bot-bridge idempotency.

The tests are static-introspection only — no DB engine required. They run
under the same SQLite-less / Postgres-less harness as the rest of the
seller tests (see ``requirements.txt``: no psycopg, no pytest_postgresql).
Where a contract is Postgres-specific (e.g. partial unique indexes via
``postgresql_where``), the test asserts on the SQLAlchemy ``Index`` object
itself, which carries the dialect-scoped predicate as a kwarg.

The CRM tables seed the Chatwoot-style 3-pane dashboard (C2/C3) that lets
human agents take over a nullclaw bot thread; the bridge↔CRM handoff
contract is enforced by C2 (FastAPI routes) and C4 (bridge code), but the
schema must already support it — see CLAUDE-C1 brief.
"""

from __future__ import annotations

import enum as py_enum

import pytest
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql.schema import Column


# ---------------------------------------------------------------------------
# Registration: importing from app.models must yield the new classes.
# ---------------------------------------------------------------------------


def test_models_importable_from_app_models():
    from app.models import (
        Channel,
        Contact,
        Conversation,
        ConversationState,
        Inbox,
        Label,
        Message,
        MessageDelivery,
        MessageSender,
    )

    assert Contact is not None
    assert Inbox is not None
    assert Conversation is not None
    assert Message is not None
    assert Label is not None
    assert Channel is not None
    assert ConversationState is not None
    assert MessageSender is not None
    assert MessageDelivery is not None


def test_tables_are_registered_in_base_metadata():
    from app.models import Base

    expected = {
        "contacts",
        "inboxes",
        "conversations",
        "messages",
        "labels",
        "conversation_labels",
    }
    assert expected.issubset(set(Base.metadata.tables.keys())), (
        f"missing CRM tables in Base.metadata.tables: "
        f"{expected - set(Base.metadata.tables.keys())}"
    )


def test_models_present_in_dunder_all():
    import app.models as m

    for name in (
        "Channel",
        "ConversationState",
        "MessageSender",
        "MessageDelivery",
        "Contact",
        "Inbox",
        "Conversation",
        "Message",
        "Label",
    ):
        assert name in m.__all__, f"{name!r} missing from app.models.__all__"


# ---------------------------------------------------------------------------
# Enums.
# ---------------------------------------------------------------------------


def test_channel_enum_values_and_name():
    from app.models import Channel

    assert issubclass(Channel, py_enum.Enum)
    assert issubclass(Channel, str)
    assert Channel.WEBSITE.value == "website"
    assert Channel.WHATSAPP.value == "whatsapp"
    assert {e.value for e in Channel} == {"website", "whatsapp"}


def test_conversation_state_enum_values_and_name():
    from app.models import ConversationState

    assert issubclass(ConversationState, py_enum.Enum)
    assert issubclass(ConversationState, str)
    assert ConversationState.BOT_ACTIVE.value == "bot_active"
    assert ConversationState.HUMAN_HANDOFF.value == "human_handoff"
    assert ConversationState.RESOLVED.value == "resolved"
    assert {e.value for e in ConversationState} == {
        "bot_active",
        "human_handoff",
        "resolved",
    }


def test_message_sender_enum_values_and_name():
    from app.models import MessageSender

    assert issubclass(MessageSender, py_enum.Enum)
    assert issubclass(MessageSender, str)
    assert MessageSender.CONTACT.value == "contact"
    assert MessageSender.BOT.value == "bot"
    assert MessageSender.AGENT.value == "agent"
    assert {e.value for e in MessageSender} == {"contact", "bot", "agent"}


def test_message_delivery_enum_values_and_name():
    from app.models import MessageDelivery

    assert issubclass(MessageDelivery, py_enum.Enum)
    assert issubclass(MessageDelivery, str)
    assert MessageDelivery.NA.value == "na"
    assert MessageDelivery.PENDING.value == "pending"
    assert MessageDelivery.SENT.value == "sent"
    assert MessageDelivery.FAILED.value == "failed"
    assert {e.value for e in MessageDelivery} == {
        "na",
        "pending",
        "sent",
        "failed",
    }


# ---------------------------------------------------------------------------
# Postgres-side enum type names. The SAEnum carries a ``name`` kwarg that
# becomes the Postgres CREATE TYPE identifier; this is the wire-level shape
# C2/C4 will rely on, so we pin it.
# ---------------------------------------------------------------------------


def _enum_column_name(model, col_name: str) -> str:
    col = model.__table__.columns[col_name]
    assert isinstance(col.type, SAEnum)
    return col.type.name


def test_postgres_enum_type_names_pinned():
    from app.models import Conversation, Inbox, Message

    assert _enum_column_name(Inbox, "channel") == "conv_channel"
    assert _enum_column_name(Conversation, "channel") == "conv_channel"
    assert _enum_column_name(Conversation, "state") == "conversation_state"
    assert _enum_column_name(Message, "sender") == "message_sender"
    assert _enum_column_name(Message, "delivery") == "message_delivery"


# ---------------------------------------------------------------------------
# Contact.
# ---------------------------------------------------------------------------


def test_contact_columns():
    from app.models import Contact

    cols = Contact.__table__.columns
    assert "id" in cols
    assert isinstance(cols["id"].type, UUID)
    assert cols["id"].primary_key is True

    # store-scoped
    assert "store_id" in cols
    assert isinstance(cols["store_id"].type, UUID)
    assert cols["store_id"].nullable is False
    assert cols["store_id"].index is True
    fks = list(cols["store_id"].foreign_keys)
    assert len(fks) == 1
    assert fks[0].column.table.name == "stores"
    assert fks[0].ondelete == "CASCADE"

    # external_id — bridge idempotency key, nullable
    assert "external_id" in cols
    assert isinstance(cols["external_id"].type, String)
    assert cols["external_id"].nullable is True

    # name, email, phone, avatar_url — all nullable
    for n in ("name", "email", "phone", "avatar_url"):
        assert n in cols, f"Contact.{n} missing"
        assert cols[n].nullable is True

    # email indexed for join to orders.buyer_email
    assert cols["email"].index is True

    # attributes JSONB nullable
    assert "attributes" in cols
    assert isinstance(cols["attributes"].type, JSONB)
    assert cols["attributes"].nullable is True

    # timestamps mixin
    assert "created_at" in cols
    assert "updated_at" in cols


def test_contact_unique_partial_index_on_store_external_id():
    from app.models import Contact

    matches = [
        ix
        for ix in Contact.__table__.indexes
        if ix.unique
        and {c.name for c in ix.columns} == {"store_id", "external_id"}
    ]
    assert len(matches) == 1, (
        "expected exactly one unique partial index on "
        "Contact(store_id, external_id), got "
        f"{[(ix.name, ix.unique, {c.name for c in ix.columns}) for ix in Contact.__table__.indexes]}"
    )
    ix = matches[0]
    # postgresql_where holds the WHERE clause for the partial index.
    where = ix.dialect_kwargs.get("postgresql_where", None)
    assert where is not None, (
        "unique index on Contact(store_id, external_id) must be partial "
        "with postgresql_where=external_id IS NOT NULL for bridge idempotency"
    )


# ---------------------------------------------------------------------------
# Inbox.
# ---------------------------------------------------------------------------


def test_inbox_columns():
    from app.models import Channel, Inbox

    cols = Inbox.__table__.columns
    assert "id" in cols
    assert cols["id"].primary_key is True

    assert "store_id" in cols
    assert cols["store_id"].nullable is False
    assert cols["store_id"].index is True
    fks = list(cols["store_id"].foreign_keys)
    assert len(fks) == 1
    assert fks[0].column.table.name == "stores"
    assert fks[0].ondelete == "CASCADE"

    assert "name" in cols
    assert isinstance(cols["name"].type, String)
    assert cols["name"].nullable is False

    assert "channel" in cols
    assert isinstance(cols["channel"].type, SAEnum)
    # the enum's python_type points at the Channel class
    assert cols["channel"].type.python_type is Channel

    assert "config" in cols
    assert isinstance(cols["config"].type, JSONB)
    assert cols["config"].nullable is True


# ---------------------------------------------------------------------------
# Conversation.
# ---------------------------------------------------------------------------


def test_conversation_columns_and_fks():
    from app.models import Channel, Conversation, ConversationState

    cols = Conversation.__table__.columns
    assert cols["id"].primary_key is True

    # FK to stores (CASCADE)
    assert cols["store_id"].nullable is False
    assert cols["store_id"].index is True
    fk_store = list(cols["store_id"].foreign_keys)[0]
    assert fk_store.column.table.name == "stores"
    assert fk_store.ondelete == "CASCADE"

    # FK to inboxes (CASCADE)
    assert "inbox_id" in cols
    fk_inbox = list(cols["inbox_id"].foreign_keys)[0]
    assert fk_inbox.column.table.name == "inboxes"
    assert fk_inbox.ondelete == "CASCADE"

    # FK to contacts (CASCADE)
    assert "contact_id" in cols
    fk_contact = list(cols["contact_id"].foreign_keys)[0]
    assert fk_contact.column.table.name == "contacts"
    assert fk_contact.ondelete == "CASCADE"

    # channel enum reuses conv_channel
    assert isinstance(cols["channel"].type, SAEnum)
    assert cols["channel"].type.python_type is Channel
    assert cols["channel"].type.name == "conv_channel"

    # state enum w/ default BOT_ACTIVE + indexed
    assert isinstance(cols["state"].type, SAEnum)
    assert cols["state"].type.python_type is ConversationState
    assert cols["state"].index is True
    default = cols["state"].default
    assert default is not None
    assert default.arg is ConversationState.BOT_ACTIVE

    # external_id nullable (bridge stable id)
    assert cols["external_id"].nullable is True

    # assignee_user_id FK → users (SET NULL), nullable
    assert "assignee_user_id" in cols
    assert cols["assignee_user_id"].nullable is True
    fk_assignee = list(cols["assignee_user_id"].foreign_keys)[0]
    assert fk_assignee.column.table.name == "users"
    assert fk_assignee.ondelete == "SET NULL"

    # last_message_at indexed (inbox sort)
    assert "last_message_at" in cols
    assert cols["last_message_at"].index is True

    # last_message_preview — string ≤ 280
    assert "last_message_preview" in cols
    assert isinstance(cols["last_message_preview"].type, String)
    assert cols["last_message_preview"].type.length is not None
    assert cols["last_message_preview"].type.length <= 280

    # unread_agent_count default 0
    assert "unread_agent_count" in cols
    assert cols["unread_agent_count"].default.arg == 0

    # handoff_at, resolved_at — nullable timestamps
    assert cols["handoff_at"].nullable is True
    assert cols["resolved_at"].nullable is True


def test_conversation_unique_partial_index_on_store_external_id():
    from app.models import Conversation

    matches = [
        ix
        for ix in Conversation.__table__.indexes
        if ix.unique
        and {c.name for c in ix.columns} == {"store_id", "external_id"}
    ]
    assert len(matches) == 1, (
        "expected unique partial index on "
        "Conversation(store_id, external_id)"
    )
    where = matches[0].dialect_kwargs.get("postgresql_where", None)
    assert where is not None, (
        "Conversation idempotency index must be partial "
        "(postgresql_where=external_id IS NOT NULL)"
    )


# ---------------------------------------------------------------------------
# Message.
# ---------------------------------------------------------------------------


def test_message_columns_and_fks():
    from app.models import Message, MessageDelivery, MessageSender

    cols = Message.__table__.columns

    # FK to conversations CASCADE, indexed
    assert cols["conversation_id"].nullable is False
    assert cols["conversation_id"].index is True
    fk_conv = list(cols["conversation_id"].foreign_keys)[0]
    assert fk_conv.column.table.name == "conversations"
    assert fk_conv.ondelete == "CASCADE"

    # store_id denormalized for fast store-scoped CRM queries, CASCADE
    assert cols["store_id"].nullable is False
    assert cols["store_id"].index is True
    fk_store = list(cols["store_id"].foreign_keys)[0]
    assert fk_store.column.table.name == "stores"
    assert fk_store.ondelete == "CASCADE"

    # sender enum
    assert isinstance(cols["sender"].type, SAEnum)
    assert cols["sender"].type.python_type is MessageSender

    # sender_user_id FK → users SET NULL, nullable (only set for agent msgs)
    assert "sender_user_id" in cols
    assert cols["sender_user_id"].nullable is True
    fk_su = list(cols["sender_user_id"].foreign_keys)[0]
    assert fk_su.column.table.name == "users"
    assert fk_su.ondelete == "SET NULL"

    # content JSONB not null
    assert isinstance(cols["content"].type, JSONB)
    assert cols["content"].nullable is False

    # external_id nullable
    assert cols["external_id"].nullable is True

    # delivery enum w/ default NA + indexed
    assert isinstance(cols["delivery"].type, SAEnum)
    assert cols["delivery"].type.python_type is MessageDelivery
    assert cols["delivery"].index is True
    assert cols["delivery"].default.arg is MessageDelivery.NA

    # delivered_at nullable
    assert cols["delivered_at"].nullable is True


def test_message_unique_partial_index_on_conversation_external_id():
    from app.models import Message

    matches = [
        ix
        for ix in Message.__table__.indexes
        if ix.unique
        and {c.name for c in ix.columns}
        == {"conversation_id", "external_id"}
    ]
    assert len(matches) == 1, (
        "expected unique partial index on "
        "Message(conversation_id, external_id)"
    )
    where = matches[0].dialect_kwargs.get("postgresql_where", None)
    assert where is not None, (
        "Message idempotency index must be partial "
        "(postgresql_where=external_id IS NOT NULL)"
    )


# ---------------------------------------------------------------------------
# Label and conversation_labels join.
# ---------------------------------------------------------------------------


def test_label_columns():
    from app.models import Label

    cols = Label.__table__.columns
    assert cols["id"].primary_key is True

    assert cols["store_id"].nullable is False
    assert cols["store_id"].index is True
    fk = list(cols["store_id"].foreign_keys)[0]
    assert fk.column.table.name == "stores"
    assert fk.ondelete == "CASCADE"

    assert cols["name"].nullable is False
    assert isinstance(cols["name"].type, String)

    # color hex (≤ 16 chars), nullable
    assert cols["color"].nullable is True
    assert isinstance(cols["color"].type, String)
    assert cols["color"].type.length is not None
    assert cols["color"].type.length <= 16


def test_label_unique_index_on_store_name():
    from app.models import Label

    matches = [
        ix
        for ix in Label.__table__.indexes
        if ix.unique and {c.name for c in ix.columns} == {"store_id", "name"}
    ]
    assert len(matches) == 1, (
        "expected unique index on Label(store_id, name), got "
        f"{[(ix.name, ix.unique, {c.name for c in ix.columns}) for ix in Label.__table__.indexes]}"
    )


def test_conversation_labels_join_table():
    from app.models import Base

    assert "conversation_labels" in Base.metadata.tables, (
        "conversation_labels join table must be registered in Base.metadata"
    )
    t = Base.metadata.tables["conversation_labels"]

    # exactly two PK columns: conversation_id, label_id
    pk_names = {c.name for c in t.primary_key.columns}
    assert pk_names == {"conversation_id", "label_id"}, (
        f"conversation_labels PK should be (conversation_id, label_id); got {pk_names}"
    )

    # both FKs ondelete=CASCADE
    conv_col = t.c["conversation_id"]
    label_col = t.c["label_id"]
    fk_conv = list(conv_col.foreign_keys)[0]
    fk_label = list(label_col.foreign_keys)[0]
    assert fk_conv.column.table.name == "conversations"
    assert fk_conv.ondelete == "CASCADE"
    assert fk_label.column.table.name == "labels"
    assert fk_label.ondelete == "CASCADE"


# ---------------------------------------------------------------------------
# Defaults sanity.
# ---------------------------------------------------------------------------


def test_conversation_state_default_is_bot_active():
    from app.models import Conversation, ConversationState

    col = Conversation.__table__.columns["state"]
    assert col.default is not None
    assert col.default.arg is ConversationState.BOT_ACTIVE


def test_message_delivery_default_is_na():
    from app.models import Message, MessageDelivery

    col = Message.__table__.columns["delivery"]
    assert col.default is not None
    assert col.default.arg is MessageDelivery.NA


def test_conversation_unread_agent_count_defaults_to_zero():
    from app.models import Conversation

    col = Conversation.__table__.columns["unread_agent_count"]
    assert col.default is not None
    assert col.default.arg == 0


# ---------------------------------------------------------------------------
# Idempotency contract test — Postgres-only (partial-unique-index semantics).
#
# In a Postgres-backed setup, inserting two Conversations / Messages with the
# same (store_id, external_id) / (conversation_id, external_id) must violate
# the partial unique index. We don't have Postgres locally in CI (no psycopg
# in requirements.txt — only asyncpg, which isn't a pytest_postgresql fixture
# provider), so this test is gated: it skips when no postgres DSN is wired
# via env (CRM_TEST_PG_DSN). When present, it asserts the IntegrityError.
# C2/C4 will exercise the same contract via the live Neon DB.
# ---------------------------------------------------------------------------


def test_idempotency_contract_postgres_only(monkeypatch):
    import os

    dsn = os.environ.get("CRM_TEST_PG_DSN")
    if not dsn:
        pytest.skip(
            "CRM_TEST_PG_DSN not set; partial-unique-index idempotency "
            "contract is enforced by Postgres only. Run with "
            "CRM_TEST_PG_DSN=postgresql+psycopg://… to exercise it. "
            "C2/C4 cover this against Neon."
        )

    # Lazy import — running this body would need psycopg/asyncpg.
    import uuid

    from sqlalchemy import create_engine
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session

    from app.models import (
        Base,
        Channel,
        Contact,
        Conversation,
        Inbox,
        Message,
        MessageSender,
        Store,
    )

    eng = create_engine(dsn)
    Base.metadata.create_all(eng)
    try:
        with Session(eng) as s:
            store = Store(
                subscriber_id=f"test-{uuid.uuid4()}.local",
                subscriber_url="http://localhost",
                name="t",
            )
            s.add(store)
            s.flush()
            inbox = Inbox(store_id=store.id, name="web", channel=Channel.WEBSITE)
            contact = Contact(store_id=store.id, external_id="dup-ext")
            s.add_all([inbox, contact])
            s.flush()
            c1 = Conversation(
                store_id=store.id,
                inbox_id=inbox.id,
                contact_id=contact.id,
                channel=Channel.WEBSITE,
                external_id="dup-conv",
            )
            s.add(c1)
            s.flush()
            c2 = Conversation(
                store_id=store.id,
                inbox_id=inbox.id,
                contact_id=contact.id,
                channel=Channel.WEBSITE,
                external_id="dup-conv",
            )
            s.add(c2)
            with pytest.raises(IntegrityError):
                s.flush()
            s.rollback()

            # Message idempotency
            m1 = Message(
                conversation_id=c1.id,
                store_id=store.id,
                sender=MessageSender.CONTACT,
                content={"text": "hi"},
                external_id="dup-msg",
            )
            s.add(m1)
            s.flush()
            m2 = Message(
                conversation_id=c1.id,
                store_id=store.id,
                sender=MessageSender.CONTACT,
                content={"text": "hi again"},
                external_id="dup-msg",
            )
            s.add(m2)
            with pytest.raises(IntegrityError):
                s.flush()
            s.rollback()
    finally:
        Base.metadata.drop_all(eng)
        eng.dispose()


# ---------------------------------------------------------------------------
# add-crm-tables.py — idempotent operator script (dry-run-default).
# ---------------------------------------------------------------------------


def test_add_crm_tables_script_exists_and_imports():
    import importlib.util
    import sys
    from pathlib import Path

    p = Path(__file__).resolve().parent.parent / "scripts" / "add-crm-tables.py"
    assert p.exists(), f"missing operator script {p}"

    spec = importlib.util.spec_from_file_location("add_crm_tables", p)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["add_crm_tables"] = mod
    spec.loader.exec_module(mod)
    assert hasattr(mod, "print_dry_run_sql")


def test_add_crm_tables_dry_run_emits_create_for_each_table():
    import importlib.util
    import io
    import sys
    from contextlib import redirect_stdout
    from pathlib import Path

    p = Path(__file__).resolve().parent.parent / "scripts" / "add-crm-tables.py"
    spec = importlib.util.spec_from_file_location("add_crm_tables", p)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["add_crm_tables"] = mod
    spec.loader.exec_module(mod)

    buf = io.StringIO()
    with redirect_stdout(buf):
        mod.print_dry_run_sql()
    out = buf.getvalue()
    for table in (
        "contacts",
        "inboxes",
        "conversations",
        "messages",
        "labels",
        "conversation_labels",
    ):
        assert f"CREATE TABLE {table}" in out, (
            f"dry-run SQL must include CREATE TABLE for {table}; "
            f"got:\n{out}"
        )
    # The CREATE TYPE statements for our four enums must also appear.
    for enum_name in (
        "conv_channel",
        "conversation_state",
        "message_sender",
        "message_delivery",
    ):
        assert enum_name in out, (
            f"dry-run SQL must mention enum type {enum_name}; got:\n{out}"
        )


def test_add_crm_tables_apply_requires_database_url(monkeypatch):
    import importlib.util
    import sys
    from pathlib import Path

    p = Path(__file__).resolve().parent.parent / "scripts" / "add-crm-tables.py"
    spec = importlib.util.spec_from_file_location("add_crm_tables", p)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["add_crm_tables"] = mod
    spec.loader.exec_module(mod)

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(sys, "argv", ["add-crm-tables.py", "--apply"])
    rc = mod.main()
    assert rc != 0
