"""Task C2 — Chatwoot-style CRM FastAPI routes.

These tests pin the CRM-write contract owned by ``app/api/conversations.py``
plus its companions (contacts, inboxes, labels):

* Routes are registered on the FastAPI app with the right method + auth
  + scope shape.
* Serializers stringify UUIDs, enums → ``.value``, datetimes → ISO 8601.
* The headline-atomicity contract: ``POST /conversations/{id}/messages``
  inserts the agent message AND flips ``state→human_handoff`` in one
  transaction so the bridge can never observe one without the other.
* The auth boundary: super-admin may omit ``store_id``; non-super must
  pass an accessible one (400 / 403 otherwise).
* The state machine: take-over / assign / resolve / reopen behave
  idempotently and refuse cross-store assignment.
* Labels: attach is idempotent (ON CONFLICT DO NOTHING) and cross-store
  rejected; detach returns 204 either way.

Test style
----------
The seller test rig has no pytest-asyncio, no aiosqlite, no psycopg — just
``asyncio.run`` + stubs (see ``tests/test_seller_handler_ondc_tags.py``).
We follow that pattern:

* **Route-shape tests** introspect ``app.routes`` so they need no DB.
* **Serializer / helper tests** are pure-Python.
* **Behavioural tests** dispatch directly into the route function with a
  fake AsyncSession that captures writes — this lets us exercise the
  state machine + transaction semantics without standing up Postgres.
* **PG-gated integration tests** (skipped when ``CRM_TEST_PG_DSN`` is
  unset) round-trip the same contract through a live Postgres so the
  ``SELECT ... FOR UPDATE`` lock + partial-unique-index idempotency
  actually run. Matches the pattern in
  ``tests/test_crm_schema.py:test_idempotency_contract_postgres_only``.
"""

from __future__ import annotations

import asyncio
import os
import sys
import types
import uuid
from datetime import datetime, timezone
from typing import Any

import pytest


# Make app and packages importable regardless of how pytest is invoked.
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PROTO = os.path.join(_ROOT, "packages", "beckn-protocol")
for _p in (_ROOT, _PROTO):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ---------------------------------------------------------------------------
# Module import surface
# ---------------------------------------------------------------------------


def test_modules_importable():
    from app.api import conversations, contacts, inboxes, labels

    assert hasattr(conversations, "router")
    assert hasattr(contacts, "router")
    assert hasattr(inboxes, "router")
    assert hasattr(labels, "router")


def test_router_prefixes_match_brief():
    """Routers carry path-only prefixes; ``/api`` is added in main.py."""
    from app.api.conversations import router as conv_router
    from app.api.contacts import router as contacts_router
    from app.api.inboxes import router as inboxes_router
    from app.api.labels import router as labels_router

    assert conv_router.prefix == "/conversations"
    assert contacts_router.prefix == "/contacts"
    assert inboxes_router.prefix == "/inboxes"
    assert labels_router.prefix == "/labels"


# ---------------------------------------------------------------------------
# Registration on the FastAPI app
# ---------------------------------------------------------------------------


def _app():
    """Import the FastAPI app, defaulting DATABASE_URL so engine init works."""
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    from app.main import app

    return app


def _routes_by_path(app) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for r in app.routes:
        if hasattr(r, "path") and hasattr(r, "methods"):
            out.setdefault(r.path, set()).update(r.methods or set())
    return out


def test_all_crm_routes_registered():
    routes = _routes_by_path(_app())

    expected = {
        # conversations
        ("/api/conversations", "GET"),
        ("/api/conversations/{conversation_id}", "GET"),
        ("/api/conversations/{conversation_id}/messages", "GET"),
        ("/api/conversations/{conversation_id}/messages", "POST"),
        ("/api/conversations/{conversation_id}/take-over", "POST"),
        ("/api/conversations/{conversation_id}/assign", "POST"),
        ("/api/conversations/{conversation_id}/resolve", "POST"),
        ("/api/conversations/{conversation_id}/reopen", "POST"),
        ("/api/conversations/{conversation_id}/labels", "POST"),
        ("/api/conversations/{conversation_id}/labels/{label_id}", "DELETE"),
        # contacts
        ("/api/contacts", "GET"),
        ("/api/contacts/{contact_id}", "GET"),
        # inboxes
        ("/api/inboxes", "GET"),
        ("/api/inboxes", "POST"),
        # labels
        ("/api/labels", "GET"),
        ("/api/labels", "POST"),
    }
    for path, method in expected:
        assert path in routes, f"route missing: {method} {path}"
        assert method in routes[path], (
            f"method {method} not on {path}; got {routes[path]}"
        )


def test_crm_routes_not_in_cacheable_prefixes():
    """C2 resources are mutable — they MUST NOT carry the SWR cache header.

    Brief: "Do NOT add to ``_CACHEABLE_PREFIXES``". We assert the prefix
    list explicitly so a future refactor can't silently add ``/api/
    conversations`` (which would let a stale POST/GET poll show up to 15s
    of stale handoff state to the bridge — the exact race we're locking
    down here).
    """
    from app.main import _CACHEABLE_PREFIXES

    for p in ("/api/conversations", "/api/contacts", "/api/inboxes", "/api/labels"):
        assert p not in _CACHEABLE_PREFIXES, (
            f"{p} must not be cacheable — it's a mutable CRM resource"
        )


# ---------------------------------------------------------------------------
# Serializers — pure-python: pin UUIDs → str, enums → .value, datetimes ISO.
# ---------------------------------------------------------------------------


def _make_conv(
    state: "ConversationState | None" = None,
    *,
    last_message_at: datetime | None = None,
    last_message_preview: str | None = None,
    handoff_at: datetime | None = None,
    resolved_at: datetime | None = None,
    assignee_user_id: uuid.UUID | None = None,
    unread_agent_count: int = 0,
) -> Any:
    from app.models import Channel, ConversationState

    if state is None:
        state = ConversationState.BOT_ACTIVE
    return types.SimpleNamespace(
        id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        store_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        inbox_id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
        contact_id=uuid.UUID("44444444-4444-4444-4444-444444444444"),
        channel=Channel.WEBSITE,
        state=state,
        external_id="ext-1",
        assignee_user_id=assignee_user_id,
        last_message_at=last_message_at,
        last_message_preview=last_message_preview,
        unread_agent_count=unread_agent_count,
        handoff_at=handoff_at,
        resolved_at=resolved_at,
        created_at=datetime(2026, 5, 19, 12, 0, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 5, 19, 12, 30, 0, tzinfo=timezone.utc),
    )


def _make_msg(
    sender: "MessageSender | None" = None,
    delivery: "MessageDelivery | None" = None,
    content: dict[str, Any] | None = None,
) -> Any:
    from app.models import MessageDelivery, MessageSender

    return types.SimpleNamespace(
        id=uuid.UUID("55555555-5555-5555-5555-555555555555"),
        conversation_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        store_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        sender=sender or MessageSender.AGENT,
        sender_user_id=uuid.UUID("66666666-6666-6666-6666-666666666666"),
        content=content or {"text": "hi"},
        external_id=None,
        delivery=delivery or MessageDelivery.PENDING,
        delivered_at=None,
        created_at=datetime(2026, 5, 19, 12, 0, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 5, 19, 12, 0, 0, tzinfo=timezone.utc),
    )


class TestSerializers:
    def test_conversation_uuids_become_strings(self):
        from app.api.conversations import _serialize_conversation

        out = _serialize_conversation(_make_conv())
        for k in ("id", "store_id", "inbox_id", "contact_id"):
            assert isinstance(out[k], str)
            uuid.UUID(out[k])  # parse-back to ensure they're real UUIDs

    def test_conversation_enums_become_values(self):
        from app.api.conversations import _serialize_conversation

        out = _serialize_conversation(_make_conv())
        assert out["state"] == "bot_active"
        assert out["channel"] == "website"

    def test_conversation_datetimes_are_iso(self):
        from app.api.conversations import _serialize_conversation

        out = _serialize_conversation(_make_conv())
        # Round-trip-parse the timestamp to confirm it's ISO 8601.
        datetime.fromisoformat(out["created_at"])
        datetime.fromisoformat(out["updated_at"])

    def test_conversation_nullable_fields_pass_through_as_none(self):
        from app.api.conversations import _serialize_conversation

        out = _serialize_conversation(_make_conv())
        assert out["handoff_at"] is None
        assert out["resolved_at"] is None
        assert out["assignee_user_id"] is None

    def test_message_serializer_shape(self):
        from app.api.conversations import _serialize_message

        out = _serialize_message(_make_msg())
        assert out["sender"] == "agent"
        assert out["delivery"] == "pending"
        assert out["content"] == {"text": "hi"}
        assert isinstance(out["id"], str)
        assert isinstance(out["sender_user_id"], str)

    def test_message_content_jsonb_passes_through_unchanged(self):
        from app.api.conversations import _serialize_message

        content = {
            "text": "Sure!",
            "blocks": [
                {"type": "product_card", "product_id": "abc"},
                {"type": "image", "url": "https://example.com/x.png"},
            ],
        }
        out = _serialize_message(_make_msg(content=content))
        assert out["content"] == content


class TestTruncatePreview:
    """The schema column is ``String(280)``; writer must truncate at 280."""

    def test_short_text_passes_through(self):
        from app.api.conversations import _truncate_preview

        assert _truncate_preview("hi") == "hi"

    def test_exactly_280_passes_through(self):
        from app.api.conversations import _truncate_preview

        s = "x" * 280
        assert _truncate_preview(s) == s

    def test_over_280_is_truncated_to_280(self):
        from app.api.conversations import _truncate_preview

        s = "x" * 281
        out = _truncate_preview(s)
        assert out is not None
        assert len(out) == 280

    def test_none_returns_none(self):
        from app.api.conversations import _truncate_preview

        assert _truncate_preview(None) is None


# ---------------------------------------------------------------------------
# Auth boundary — ``_resolve_store_scope`` is the single chokepoint that
# normalises the super-admin vs scoped-user contract. Exercising it
# directly lets us pin the brief's 400 / 403 / 200-all-stores semantics
# without an HTTP layer.
# ---------------------------------------------------------------------------


def _fake_user(*, is_super_admin: bool, user_id: uuid.UUID | None = None) -> Any:
    return types.SimpleNamespace(
        id=user_id or uuid.uuid4(),
        is_super_admin=is_super_admin,
        email="x@example.com",
    )


class _AccessibleDB:
    """A db stub whose can_access_store-equivalent always allows."""

    pass


class _DenyDB:
    pass


def _patch_can_access(monkeypatch, allow: bool):
    """Patch can_access_store on the module under test."""
    async def _stub(_db, _user, _store_id, **kw):
        return allow

    from app.api import conversations as conv_mod

    monkeypatch.setattr(conv_mod, "can_access_store", _stub)


class TestStoreScopeResolution:
    def test_super_admin_without_store_id_yields_none(self, monkeypatch):
        from app.api.conversations import _resolve_store_scope

        _patch_can_access(monkeypatch, True)
        user = _fake_user(is_super_admin=True)
        out = asyncio.run(_resolve_store_scope(None, user, None))
        assert out is None

    def test_super_admin_with_store_id_passes_through(self, monkeypatch):
        from app.api.conversations import _resolve_store_scope

        _patch_can_access(monkeypatch, False)  # not consulted for super-admin
        user = _fake_user(is_super_admin=True)
        sid = uuid.uuid4()
        out = asyncio.run(_resolve_store_scope(None, user, sid))
        assert out == sid

    def test_non_super_without_store_id_is_400(self, monkeypatch):
        from fastapi import HTTPException
        from app.api.conversations import _resolve_store_scope

        _patch_can_access(monkeypatch, True)
        user = _fake_user(is_super_admin=False)
        with pytest.raises(HTTPException) as exc:
            asyncio.run(_resolve_store_scope(None, user, None))
        assert exc.value.status_code == 400
        assert "store_id" in str(exc.value.detail).lower()

    def test_non_super_with_inaccessible_store_is_403(self, monkeypatch):
        from fastapi import HTTPException
        from app.api.conversations import _resolve_store_scope

        _patch_can_access(monkeypatch, False)
        user = _fake_user(is_super_admin=False)
        with pytest.raises(HTTPException) as exc:
            asyncio.run(_resolve_store_scope(None, user, uuid.uuid4()))
        assert exc.value.status_code == 403

    def test_non_super_with_accessible_store_returns_it(self, monkeypatch):
        from app.api.conversations import _resolve_store_scope

        _patch_can_access(monkeypatch, True)
        user = _fake_user(is_super_admin=False)
        sid = uuid.uuid4()
        out = asyncio.run(_resolve_store_scope(None, user, sid))
        assert out == sid


# ---------------------------------------------------------------------------
# State-machine + handoff atomicity — driven via a fake AsyncSession that
# records writes. Lets us exercise the POST /messages contract end-to-end
# without Postgres, and verify the per-state branching behaviour.
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, obj):
        self._obj = obj

    def scalar_one_or_none(self):
        return self._obj

    def scalars(self):
        return self

    def all(self):
        if self._obj is None:
            return []
        return list(self._obj) if isinstance(self._obj, (list, tuple)) else [self._obj]


class _FakeDB:
    """Async-session stand-in that drives the routes under test.

    Each ``execute`` consults a queue of pre-staged results; ``add``,
    ``flush``, ``refresh``, ``commit``, ``rollback`` are recorded so the
    test can assert which side-effects landed and in what order.

    ``raise_on_flush`` lets a test simulate a mid-transaction failure;
    when set, the second flush() raises — covering the headline
    atomicity contract (the agent-msg INSERT AND the state UPDATE must
    roll back together).
    """

    def __init__(self, results: list[Any] | None = None):
        self.results = list(results or [])
        self.added: list[Any] = []
        self.flushes = 0
        self.commits = 0
        self.rollbacks = 0
        self.refreshed: list[Any] = []
        self.executed_statements: list[Any] = []
        self.raise_on_flush: int | None = None  # 1-based flush index to fail on

    async def execute(self, stmt):
        self.executed_statements.append(stmt)
        if self.results:
            return _FakeResult(self.results.pop(0))
        return _FakeResult(None)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushes += 1
        if self.raise_on_flush is not None and self.flushes == self.raise_on_flush:
            raise RuntimeError("simulated mid-transaction failure")

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1

    async def refresh(self, obj):
        self.refreshed.append(obj)


class TestPostAgentMessageHeadlineContract:
    """The atomic state-flip + message-insert contract POST /messages owns.

    These tests drive the route handler with a fake AsyncSession so we can
    assert the contract without needing Postgres. The PG-gated test below
    exercises the same path against a real DB to confirm ``FOR UPDATE``
    and transaction isolation actually work.
    """

    def _user(self):
        return _fake_user(is_super_admin=True)

    def test_bot_active_flips_to_human_handoff_and_inserts_message(
        self, monkeypatch
    ):
        from app.api.conversations import post_agent_message, PostMessageBody, MessageContent
        from app.models import ConversationState, MessageDelivery, MessageSender

        conv = _make_conv(state=ConversationState.BOT_ACTIVE)
        # First execute() loads the conversation; we then add() a Message.
        db = _FakeDB(results=[conv])
        body = PostMessageBody(content=MessageContent(text="Hi from agent!"))

        user = self._user()
        out = asyncio.run(post_agent_message(conv.id, body, user, db))

        # 1) A new Message was added to the session.
        assert len(db.added) == 1
        msg = db.added[0]
        # ...with the right shape: sender=agent, sender_user_id=user.id,
        # delivery=pending, content carries text + (optional) blocks.
        assert msg.sender is MessageSender.AGENT
        assert msg.sender_user_id == user.id
        assert msg.delivery is MessageDelivery.PENDING
        assert msg.conversation_id == conv.id
        assert msg.store_id == conv.store_id
        assert msg.content["text"] == "Hi from agent!"

        # 2) Conversation flipped to HUMAN_HANDOFF in the SAME transaction.
        assert conv.state is ConversationState.HUMAN_HANDOFF
        assert conv.handoff_at is not None
        assert conv.assignee_user_id == user.id
        # 3) Preview / counters updated.
        assert conv.last_message_at is not None
        assert conv.last_message_preview == "Hi from agent!"
        assert conv.unread_agent_count == 0

        # 4) Flush() was called exactly once — the two writes are batched.
        assert db.flushes == 1
        # The route does NOT call commit() itself — get_db() does that on
        # return (so a downstream exception still rolls everything back).
        assert db.commits == 0

        # 5) Response carries serialized message.
        assert out["data"]["sender"] == "agent"
        assert out["data"]["delivery"] == "pending"

    def test_human_handoff_does_not_clobber_handoff_at_or_assignee(
        self, monkeypatch
    ):
        from app.api.conversations import post_agent_message, PostMessageBody, MessageContent
        from app.models import ConversationState

        original_handoff_at = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
        original_assignee = uuid.uuid4()
        conv = _make_conv(
            state=ConversationState.HUMAN_HANDOFF,
            handoff_at=original_handoff_at,
            assignee_user_id=original_assignee,
        )
        db = _FakeDB(results=[conv])
        body = PostMessageBody(content=MessageContent(text="follow-up"))
        user = self._user()

        asyncio.run(post_agent_message(conv.id, body, user, db))

        assert conv.state is ConversationState.HUMAN_HANDOFF
        # CRITICAL: the original handoff_at and assignee_user_id stay put.
        # The contract: a second agent message on an already-human thread
        # only adds a message; it doesn't re-stamp who took it over.
        assert conv.handoff_at == original_handoff_at
        assert conv.assignee_user_id == original_assignee

    def test_resolved_returns_409(self, monkeypatch):
        from fastapi import HTTPException
        from app.api.conversations import post_agent_message, PostMessageBody, MessageContent
        from app.models import ConversationState

        conv = _make_conv(state=ConversationState.RESOLVED)
        db = _FakeDB(results=[conv])
        body = PostMessageBody(content=MessageContent(text="x"))
        user = self._user()

        with pytest.raises(HTTPException) as exc:
            asyncio.run(post_agent_message(conv.id, body, user, db))
        assert exc.value.status_code == 409
        assert "reopen" in str(exc.value.detail).lower()
        # No message was added; no state changed.
        assert db.added == []
        assert conv.state is ConversationState.RESOLVED

    def test_last_message_preview_truncated_to_280(self, monkeypatch):
        """Writer-side truncation: the column is String(280); we cut before
        insert so a 500-char body can't trip a Postgres length constraint."""
        from app.api.conversations import post_agent_message, PostMessageBody, MessageContent
        from app.models import ConversationState

        conv = _make_conv(state=ConversationState.BOT_ACTIVE)
        db = _FakeDB(results=[conv])
        body = PostMessageBody(content=MessageContent(text="x" * 500))
        user = self._user()

        asyncio.run(post_agent_message(conv.id, body, user, db))

        assert conv.last_message_preview is not None
        assert len(conv.last_message_preview) == 280

    def test_mid_transaction_failure_propagates_so_get_db_rolls_back(
        self, monkeypatch
    ):
        """Headline atomicity proof.

        We stage the flake by making ``flush()`` raise after the message is
        added and the state is flipped (the Python-level state is still in
        the open transaction; ``get_db()`` will roll it back). The route
        MUST let the exception propagate so the wrapping ``get_db()``
        rolls BOTH the message INSERT and the state UPDATE back together.

        If the route swallowed the exception (or committed in between),
        the bridge could observe a fresh agent message with the
        conversation still ``state=bot_active`` — and reply on top of the
        human. That's the race we're locking down here.
        """
        from app.api.conversations import post_agent_message, PostMessageBody, MessageContent
        from app.models import ConversationState

        conv = _make_conv(state=ConversationState.BOT_ACTIVE)
        db = _FakeDB(results=[conv])
        db.raise_on_flush = 1  # the first (and only) flush raises
        body = PostMessageBody(content=MessageContent(text="boom"))
        user = self._user()

        with pytest.raises(RuntimeError, match="simulated"):
            asyncio.run(post_agent_message(conv.id, body, user, db))

        # The route did NOT call commit() itself — get_db() would have
        # rolled back on the exception. We assert the contract: commit
        # never happened in the route, AND the route did not silently
        # call rollback() to "recover" (which would have ended the txn
        # mid-flight without the test layer noticing).
        assert db.commits == 0
        assert db.rollbacks == 0  # get_db's wrapper handles rollback


# ---------------------------------------------------------------------------
# take-over / resolve / reopen / assign — state-transition idempotency
# ---------------------------------------------------------------------------


class TestTakeOver:
    def test_bot_active_to_human_handoff(self, monkeypatch):
        from app.api.conversations import take_over
        from app.models import ConversationState

        conv = _make_conv(state=ConversationState.BOT_ACTIVE)
        db = _FakeDB(results=[conv])
        user = _fake_user(is_super_admin=True)
        out = asyncio.run(take_over(conv.id, user, db))
        assert conv.state is ConversationState.HUMAN_HANDOFF
        assert conv.handoff_at is not None
        assert conv.assignee_user_id == user.id
        assert out["data"]["state"] == "human_handoff"

    def test_human_handoff_is_idempotent(self, monkeypatch):
        from app.api.conversations import take_over
        from app.models import ConversationState

        original_assignee = uuid.uuid4()
        original_handoff_at = datetime(2026, 5, 1, tzinfo=timezone.utc)
        conv = _make_conv(
            state=ConversationState.HUMAN_HANDOFF,
            handoff_at=original_handoff_at,
            assignee_user_id=original_assignee,
        )
        db = _FakeDB(results=[conv])
        user = _fake_user(is_super_admin=True)
        asyncio.run(take_over(conv.id, user, db))
        # Idempotent: the calling user is NOT promoted to assignee, and
        # handoff_at is NOT re-stamped.
        assert conv.assignee_user_id == original_assignee
        assert conv.handoff_at == original_handoff_at
        # No flush() — there was nothing to write.
        assert db.flushes == 0

    def test_resolved_returns_409(self, monkeypatch):
        from fastapi import HTTPException
        from app.api.conversations import take_over
        from app.models import ConversationState

        conv = _make_conv(state=ConversationState.RESOLVED)
        db = _FakeDB(results=[conv])
        user = _fake_user(is_super_admin=True)
        with pytest.raises(HTTPException) as exc:
            asyncio.run(take_over(conv.id, user, db))
        assert exc.value.status_code == 409


class TestResolve:
    def test_active_to_resolved(self, monkeypatch):
        from app.api.conversations import resolve
        from app.models import ConversationState

        conv = _make_conv(
            state=ConversationState.HUMAN_HANDOFF,
            assignee_user_id=uuid.uuid4(),
        )
        db = _FakeDB(results=[conv])
        user = _fake_user(is_super_admin=True)
        asyncio.run(resolve(conv.id, user, db))
        assert conv.state is ConversationState.RESOLVED
        assert conv.resolved_at is not None
        # Brief: resolve clears assignee.
        assert conv.assignee_user_id is None

    def test_already_resolved_is_idempotent(self, monkeypatch):
        from app.api.conversations import resolve
        from app.models import ConversationState

        original = datetime(2026, 5, 1, tzinfo=timezone.utc)
        conv = _make_conv(
            state=ConversationState.RESOLVED, resolved_at=original
        )
        db = _FakeDB(results=[conv])
        user = _fake_user(is_super_admin=True)
        asyncio.run(resolve(conv.id, user, db))
        assert conv.resolved_at == original
        assert db.flushes == 0


class TestReopen:
    def test_resolved_to_bot_active_preserves_assignee_and_handoff(
        self, monkeypatch
    ):
        from app.api.conversations import reopen
        from app.models import ConversationState

        original_assignee = uuid.uuid4()
        original_handoff = datetime(2026, 5, 1, tzinfo=timezone.utc)
        conv = _make_conv(
            state=ConversationState.RESOLVED,
            resolved_at=datetime(2026, 5, 2, tzinfo=timezone.utc),
            handoff_at=original_handoff,
            assignee_user_id=original_assignee,
        )
        db = _FakeDB(results=[conv])
        user = _fake_user(is_super_admin=True)
        asyncio.run(reopen(conv.id, user, db))
        assert conv.state is ConversationState.BOT_ACTIVE
        assert conv.resolved_at is None
        # Brief: don't clobber assignee_user_id / handoff_at — audit trail.
        assert conv.assignee_user_id == original_assignee
        assert conv.handoff_at == original_handoff

    def test_already_active_is_idempotent(self, monkeypatch):
        from app.api.conversations import reopen
        from app.models import ConversationState

        conv = _make_conv(state=ConversationState.BOT_ACTIVE)
        db = _FakeDB(results=[conv])
        user = _fake_user(is_super_admin=True)
        asyncio.run(reopen(conv.id, user, db))
        assert db.flushes == 0


class TestAssign:
    def test_assign_to_user_with_store_access(self, monkeypatch):
        from app.api.conversations import assign, AssignBody

        target = _fake_user(is_super_admin=False, user_id=uuid.uuid4())

        # Patch can_access_store to allow the target.
        async def _allow(_db, _user, _sid, **kw):
            return True

        from app.api import conversations as conv_mod

        monkeypatch.setattr(conv_mod, "can_access_store", _allow)

        conv = _make_conv()
        # Two execute()s: load conv, then load target user.
        db = _FakeDB(results=[conv, target])

        body = AssignBody(assignee_user_id=target.id)
        user = _fake_user(is_super_admin=True)
        asyncio.run(assign(conv.id, body, user, db))
        assert conv.assignee_user_id == target.id

    def test_assign_to_user_without_store_access_is_403(self, monkeypatch):
        from fastapi import HTTPException
        from app.api.conversations import assign, AssignBody

        target = _fake_user(is_super_admin=False, user_id=uuid.uuid4())

        async def _deny(_db, _user, _sid, **kw):
            return False

        from app.api import conversations as conv_mod

        monkeypatch.setattr(conv_mod, "can_access_store", _deny)

        conv = _make_conv()
        db = _FakeDB(results=[conv, target])

        body = AssignBody(assignee_user_id=target.id)
        user = _fake_user(is_super_admin=True)
        with pytest.raises(HTTPException) as exc:
            asyncio.run(assign(conv.id, body, user, db))
        assert exc.value.status_code == 403

    def test_assign_to_missing_user_is_404(self, monkeypatch):
        from fastapi import HTTPException
        from app.api.conversations import assign, AssignBody

        conv = _make_conv()
        # Second execute() returns None — target not found.
        db = _FakeDB(results=[conv, None])

        body = AssignBody(assignee_user_id=uuid.uuid4())
        user = _fake_user(is_super_admin=True)
        with pytest.raises(HTTPException) as exc:
            asyncio.run(assign(conv.id, body, user, db))
        assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# 404 leak-protection — non-super-admin must see 404 for inaccessible
# conversations, not 403, so we don't leak existence.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Labels — attach / detach. The DB-free path here can't exercise
# ``ON CONFLICT DO NOTHING`` (sqlite/no DB), but it CAN verify the cross-
# store rejection and the 404-leak-protection contract.
# ---------------------------------------------------------------------------


def _make_label(store_id: uuid.UUID, name: str = "vip") -> Any:
    return types.SimpleNamespace(
        id=uuid.uuid4(),
        store_id=store_id,
        name=name,
        color="#ff0000",
        created_at=datetime(2026, 5, 19, tzinfo=timezone.utc),
        updated_at=datetime(2026, 5, 19, tzinfo=timezone.utc),
    )


class TestAttachLabel:
    def test_cross_store_label_is_404(self):
        from fastapi import HTTPException
        from app.api.conversations import attach_label, AttachLabelBody

        conv = _make_conv()
        # Label belongs to a DIFFERENT store.
        label = _make_label(store_id=uuid.uuid4(), name="other-store-label")
        db = _FakeDB(results=[conv, label])

        body = AttachLabelBody(label_id=label.id)
        user = _fake_user(is_super_admin=True)
        with pytest.raises(HTTPException) as exc:
            asyncio.run(attach_label(conv.id, body, user, db))
        # 404 — not 403 — so we don't leak that the label exists elsewhere.
        assert exc.value.status_code == 404

    def test_missing_label_is_404(self):
        from fastapi import HTTPException
        from app.api.conversations import attach_label, AttachLabelBody

        conv = _make_conv()
        db = _FakeDB(results=[conv, None])
        body = AttachLabelBody(label_id=uuid.uuid4())
        user = _fake_user(is_super_admin=True)
        with pytest.raises(HTTPException) as exc:
            asyncio.run(attach_label(conv.id, body, user, db))
        assert exc.value.status_code == 404

    def test_same_store_label_attaches(self):
        from app.api.conversations import attach_label, AttachLabelBody

        conv = _make_conv()
        label = _make_label(store_id=conv.store_id, name="vip")
        db = _FakeDB(results=[conv, label])

        body = AttachLabelBody(label_id=label.id)
        user = _fake_user(is_super_admin=True)
        out = asyncio.run(attach_label(conv.id, body, user, db))
        assert out["data"]["conversation_id"] == str(conv.id)
        assert out["data"]["label_id"] == str(label.id)


# ---------------------------------------------------------------------------
# Visibility / 404-leak-protection
# ---------------------------------------------------------------------------


class TestConversationVisibilityIsolation:
    def test_load_conversation_for_inaccessible_store_returns_404(
        self, monkeypatch
    ):
        from fastapi import HTTPException
        from app.api.conversations import _load_conversation_for_user

        conv = _make_conv()
        db = _FakeDB(results=[conv])
        # Non-super-admin who has no access to conv.store_id.
        user = _fake_user(is_super_admin=False)

        async def _deny(_db, _user, _sid, **kw):
            return False

        from app.api import conversations as conv_mod

        monkeypatch.setattr(conv_mod, "can_access_store", _deny)

        with pytest.raises(HTTPException) as exc:
            asyncio.run(_load_conversation_for_user(db, user, conv.id))
        # 404, NOT 403 — we don't leak "this row exists, you just can't see it".
        assert exc.value.status_code == 404

    def test_missing_conversation_is_404(self, monkeypatch):
        from fastapi import HTTPException
        from app.api.conversations import _load_conversation_for_user

        db = _FakeDB(results=[None])
        user = _fake_user(is_super_admin=True)
        with pytest.raises(HTTPException) as exc:
            asyncio.run(_load_conversation_for_user(db, user, uuid.uuid4()))
        assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# PG-gated integration: round-trip the headline contract against a real
# Postgres. Skips cleanly when CRM_TEST_PG_DSN is unset — same gating model
# as test_crm_schema.test_idempotency_contract_postgres_only. This is the
# only test that actually exercises SELECT ... FOR UPDATE and the
# transaction-isolation semantics that the bridge will rely on.
# ---------------------------------------------------------------------------


def test_handoff_atomicity_real_postgres(monkeypatch):
    """End-to-end atomicity proof against live Postgres.

    Steps:
      1. Spin up the schema against the test DSN.
      2. Insert a store, inbox, contact, conversation (state=bot_active),
         and a User to act as the agent.
      3. Drive ``post_agent_message`` directly (route function, not HTTP)
         against an AsyncSession bound to the test DB.
      4. Assert via a fresh session: message landed AND conversation
         flipped to human_handoff.
      5. Negative path: stage an in-handler failure (the body validator
         already covers this; here we patch the route to raise after
         adding the message). Re-fetch — neither the new message nor the
         state flip should be visible.

    Skipped without ``CRM_TEST_PG_DSN``.
    """
    dsn = os.environ.get("CRM_TEST_PG_DSN")
    if not dsn:
        pytest.skip(
            "CRM_TEST_PG_DSN not set; the SELECT FOR UPDATE + transaction "
            "atomicity contract is Postgres-only. Set "
            "CRM_TEST_PG_DSN=postgresql+asyncpg://… to exercise it."
        )

    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.api.conversations import (
        MessageContent,
        PostMessageBody,
        post_agent_message,
    )
    from app.models import (
        Base,
        Channel,
        Contact,
        Conversation,
        ConversationState,
        Inbox,
        MessageSender,
        Store,
        User,
    )

    async def _run():
        engine = create_async_engine(dsn)
        Session = async_sessionmaker(engine, expire_on_commit=False)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        try:
            # Seed: store, inbox, contact, conversation, agent user.
            async with Session() as s:
                store = Store(
                    subscriber_id=f"crm-c2-{uuid.uuid4()}.local",
                    subscriber_url="http://localhost",
                    name="Test Store",
                )
                s.add(store)
                await s.flush()

                inbox = Inbox(store_id=store.id, name="web", channel=Channel.WEBSITE)
                contact = Contact(store_id=store.id, external_id="ext-1")
                user = User(
                    email=f"agent-{uuid.uuid4()}@example.com",
                    is_super_admin=True,
                )
                s.add_all([inbox, contact, user])
                await s.flush()

                conv = Conversation(
                    store_id=store.id,
                    inbox_id=inbox.id,
                    contact_id=contact.id,
                    channel=Channel.WEBSITE,
                    state=ConversationState.BOT_ACTIVE,
                    external_id="conv-1",
                )
                s.add(conv)
                await s.commit()
                conv_id = conv.id
                user_id = user.id

            # Drive the route against the live DB. The session is created
            # the same way get_db() creates it, and we await commit on
            # successful return to mimic get_db's commit-on-success.
            async with Session() as s:
                body = PostMessageBody(content=MessageContent(text="hello"))
                # Refetch user inside this session.
                user_row = (
                    await s.execute(
                        __import__("sqlalchemy")
                        .select(User)
                        .where(User.id == user_id)
                    )
                ).scalar_one()
                await post_agent_message(conv_id, body, user_row, s)
                await s.commit()

            # Verify: message exists, conversation state flipped.
            from sqlalchemy import select

            async with Session() as s:
                from app.models import Message

                msgs = (
                    await s.execute(
                        select(Message).where(Message.conversation_id == conv_id)
                    )
                ).scalars().all()
                assert len(msgs) == 1
                assert msgs[0].sender == MessageSender.AGENT

                conv_after = (
                    await s.execute(
                        select(Conversation).where(Conversation.id == conv_id)
                    )
                ).scalar_one()
                assert conv_after.state == ConversationState.HUMAN_HANDOFF
                assert conv_after.handoff_at is not None
                assert conv_after.assignee_user_id == user_id
                # last_message_preview was set.
                assert conv_after.last_message_preview == "hello"

            # Negative path: stage a mid-handler exception. We do this by
            # patching the route to raise after the message is added but
            # before commit — assert NEITHER the message NOR the state
            # flip survives. This is the headline atomicity guarantee.

            # First, set up a NEW conversation (the previous one is now
            # in human_handoff, so a flip-test won't be observable).
            async with Session() as s:
                conv2 = Conversation(
                    store_id=conv_after.store_id,
                    inbox_id=conv_after.inbox_id,
                    contact_id=conv_after.contact_id,
                    channel=Channel.WEBSITE,
                    state=ConversationState.BOT_ACTIVE,
                    external_id="conv-2",
                )
                s.add(conv2)
                await s.commit()
                conv2_id = conv2.id

            # Now drive a session that will roll back due to a raised
            # exception. We open a SAVEPOINT-less transaction and force
            # an error AFTER the handler runs.
            from sqlalchemy.exc import IntegrityError

            session2 = Session()
            try:
                async with session2.begin():
                    user_row = (
                        await session2.execute(
                            __import__("sqlalchemy")
                            .select(User)
                            .where(User.id == user_id)
                        )
                    ).scalar_one()
                    body = PostMessageBody(
                        content=MessageContent(text="should be rolled back")
                    )
                    await post_agent_message(conv2_id, body, user_row, session2)
                    # Simulate a downstream failure.
                    raise RuntimeError("simulated downstream failure")
            except RuntimeError:
                pass
            finally:
                await session2.close()

            # Re-check from a fresh session: nothing landed.
            async with Session() as s:
                from app.models import Message

                msgs = (
                    await s.execute(
                        select(Message).where(Message.conversation_id == conv2_id)
                    )
                ).scalars().all()
                assert msgs == [], (
                    "the agent message must have been rolled back together "
                    "with the state flip"
                )
                conv_check = (
                    await s.execute(
                        select(Conversation).where(Conversation.id == conv2_id)
                    )
                ).scalar_one()
                assert conv_check.state == ConversationState.BOT_ACTIVE, (
                    "if a mid-transaction failure left the state as "
                    "human_handoff, the bridge would silently stop replying "
                    "even though no agent message was delivered — exactly "
                    "the bug this atomicity contract prevents"
                )

        finally:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)
            await engine.dispose()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# C4 — agent-delivery-queue pollability (the contract piece B4 relies on).
# ---------------------------------------------------------------------------


def test_agent_message_appears_in_pending_delivery_queue(monkeypatch):
    """C4 — an agent message lands as a pollable row in the delivery queue.

    The bridge (B4) polls the messages table with::

        SELECT id, conversation_id, content
        FROM messages
        WHERE sender = 'agent' AND delivery = 'pending'
        ORDER BY created_at
        FOR UPDATE SKIP LOCKED
        LIMIT N;

    C2's headline test (``test_handoff_atomicity_real_postgres``) proves
    the *write* atomicity. This test specifically pins the *read* shape:
    after the CRM POSTs an agent message, the row IS what the bridge's
    polling query sees — same ``sender``, same ``delivery``, same content.

    Why a separate test (instead of leaning on the C2 PG test)
    -----------------------------------------------------------
    The C2 test asserts ``sender == AGENT`` via a row-select, not via the
    bridge's exact predicate (`WHERE sender='agent' AND delivery='pending'`).
    This test runs the bridge's actual query so a future regression that
    breaks the wire-level enum representation (e.g. storing 'AGENT' instead
    of 'agent' due to ``values_callable`` being dropped from the SAEnum)
    would fail HERE in the bridge's read path — not just in unrelated
    serializer tests.

    Skipped when ``CRM_TEST_PG_DSN`` is unset (matches the gating model
    of the rest of this file and ``tests/test_crm_schema.py``).
    """
    dsn = os.environ.get("CRM_TEST_PG_DSN")
    if not dsn:
        pytest.skip(
            "CRM_TEST_PG_DSN not set; pending-delivery queue pollability "
            "is Postgres-only (the bridge runs against live Postgres). "
            "Set CRM_TEST_PG_DSN=postgresql+asyncpg://… to exercise."
        )

    import asyncio

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.api.conversations import (
        MessageContent,
        PostMessageBody,
        post_agent_message,
    )
    from app.models import (
        Base,
        Channel,
        Contact,
        Conversation,
        ConversationState,
        Inbox,
        Store,
        User,
    )

    async def _run():
        engine = create_async_engine(dsn)
        Session = async_sessionmaker(engine, expire_on_commit=False)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        try:
            # Seed: store, inbox, contact, bot_active conv, agent user.
            async with Session() as s:
                store = Store(
                    subscriber_id=f"crm-c4-queue-{uuid.uuid4()}.local",
                    subscriber_url="http://localhost",
                    name="Test Store",
                )
                s.add(store)
                await s.flush()

                inbox = Inbox(
                    store_id=store.id, name="web", channel=Channel.WEBSITE
                )
                contact = Contact(store_id=store.id, external_id="ext-queue")
                user = User(
                    email=f"agent-c4-{uuid.uuid4()}@example.com",
                    is_super_admin=True,
                )
                s.add_all([inbox, contact, user])
                await s.flush()

                conv = Conversation(
                    store_id=store.id,
                    inbox_id=inbox.id,
                    contact_id=contact.id,
                    channel=Channel.WEBSITE,
                    state=ConversationState.BOT_ACTIVE,
                    external_id="conv-queue",
                )
                s.add(conv)
                await s.commit()
                conv_id = conv.id
                user_id = user.id
                store_id = store.id

            # Drive the route: agent posts a message → row should be
            # immediately pollable.
            async with Session() as s:
                from sqlalchemy import select

                user_row = (
                    await s.execute(select(User).where(User.id == user_id))
                ).scalar_one()
                body = PostMessageBody(
                    content=MessageContent(text="queued for bridge")
                )
                await post_agent_message(conv_id, body, user_row, s)
                await s.commit()

            # Now play the bridge's exact poll query. We DON'T use
            # FOR UPDATE SKIP LOCKED here because we're outside the bridge's
            # transaction model and asserting visibility, not concurrent
            # locking semantics. The PREDICATE is the contract-critical bit.
            async with Session() as s:
                rows = (
                    await s.execute(
                        text(
                            "SELECT id, conversation_id, sender::text AS sender, "
                            "delivery::text AS delivery, store_id, content "
                            "FROM messages "
                            "WHERE sender = 'agent' AND delivery = 'pending' "
                            "AND conversation_id = :cid "
                            "ORDER BY created_at"
                        ),
                        {"cid": conv_id},
                    )
                ).mappings().all()

            assert len(rows) == 1, (
                f"expected exactly one pending agent message visible to "
                f"the bridge's poll query; got {len(rows)} row(s)"
            )
            row = rows[0]
            assert row["sender"] == "agent", (
                "bridge poll predicate filters on lowercase enum VALUE; "
                f"got sender={row['sender']!r} — if this is 'AGENT' the "
                "SAEnum's values_callable has regressed (C1 contract: "
                "the enum is stored as the lowercase string the bridge "
                "queries by)"
            )
            assert row["delivery"] == "pending"
            assert row["store_id"] == store_id, (
                "denormalized store_id must match the conversation's; the "
                "bridge can filter by store_id without a join (C1 invariant)"
            )
            assert row["content"]["text"] == "queued for bridge"

            # Sanity: the conversation is now human_handoff (atomic flip),
            # so the bridge MUST NOT reply on this thread.
            from sqlalchemy import select

            async with Session() as s:
                conv_after = (
                    await s.execute(
                        select(Conversation).where(Conversation.id == conv_id)
                    )
                ).scalar_one()
                assert conv_after.state == ConversationState.HUMAN_HANDOFF, (
                    "C2 atomicity contract: the agent's POST flips state "
                    "AND inserts the message in one transaction; if state "
                    "is anything other than human_handoff here, the "
                    "transaction-boundary contract has regressed"
                )

        finally:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)
            await engine.dispose()

    asyncio.run(_run())
