#!/usr/bin/env python3
"""HTTP shim for jd-bot bridge.

Two endpoints + a health probe:

    POST /ingest    {brand, conversation_id?, customer_id, text, image_url?}
                    Upserts contact + conversation + inserts a contact
                    message. Returns {conversation_id}.

    GET  /replies?conversation=<uuid>&after=<msg_uuid>
                    Returns {messages:[...]} ordered created_at ASC.

    GET  /health    {ok:true, service:"jd-bot-bridge"}

Auth: Bearer ${BRIDGE_INGEST_TOKEN}. The token is shared with the
Vercel storefront proxy (B5's `/api/chat`); both endpoints reject if it
doesn't match. /health does NOT require auth — it's used by the
operator + by Caddy's healthcheck.

Wire shape vs. CRM schema:

    chat UI sender   ←→   CRM `messages.sender`
    -------------------------------------------
    customer              contact
    bot                   bot
    agent                 agent

The shim translates `contact ↔ customer` at the wire boundary so the
chat UI (`buyer:components/chat/types.ts`) and the CRM schema
(`seller:app/models/conversation.py`) stay in their own respective
worlds. The internal DB is always 'contact'.

Database backend:

The shim auto-detects the DSN form in DATABASE_URL:

    postgresql://… → uses psycopg2 (production)
    sqlite://…    → uses sqlite3 stdlib (smoke tests + dev fixtures)

This keeps `test/smoke.sh` runnable without Postgres while production
still uses Neon.

Brand → store_id resolution:

The `brand` field carries the storefront slug ("safiyafood"); we look up
the matching `stores.subscriber_id` ("safiyafood.jaringan-dagang.id")
to get the store_id. A small in-process cache (5 min TTL) keeps the
lookup cheap. Unknown brands → 404 with `error: 'unknown_brand'`.

Idempotency:

Every bridge-side insert carries an `external_id`. Contact:
`web-<customer_id>`. Conversation: `web-<customer_id>-<brand>` (when
new) or echoes the caller's value (when supplied). Message:
`web-msg-<random>` (since the chat UI doesn't supply one yet).
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import sys
import threading
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

# ─── Logging ──────────────────────────────────────────────────────────────
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="[jd-bot-http] %(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger("jd-bot-http")

# ─── Config ───────────────────────────────────────────────────────────────
BIND_HOST = os.environ.get("BIND_HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8088"))
DATABASE_URL = os.environ.get("DATABASE_URL", "")
INGEST_TOKEN = os.environ.get("BRIDGE_INGEST_TOKEN", "")
# Inbox the bridge writes into when it creates a new conversation. The
# operator pre-creates one inbox per (store, channel) via the CRM API
# (POST /api/inboxes). The bridge auto-resolves by (store_id, channel);
# if no inbox exists for the channel, the ingest is rejected with 503
# (matches the docs/crm-bridge-contract.md §8 "stores opt in by creating
# an inbox" rule).
STORE_LOOKUP_TTL_SEC = int(os.environ.get("STORE_LOOKUP_TTL_SEC", "300"))


# ─── DB abstraction ──────────────────────────────────────────────────────

# The shim talks to either Postgres (production) or sqlite (smoke).
# Both are exposed via the same tiny interface: `db_query(sql, params)`
# returns rows; `db_execute(sql, params)` returns rowcount; a connection
# context manager handles BEGIN/COMMIT atomicity.

def _is_sqlite(dsn: str) -> bool:
    return dsn.startswith("sqlite://") or dsn.startswith("file:")


def _is_postgres(dsn: str) -> bool:
    return dsn.startswith("postgres://") or dsn.startswith("postgresql://")


class DBBackend:
    """Thin wrapper over either psycopg2 or sqlite3.

    Both backends implement `query(sql, params) -> list[tuple]` and
    `execute_atomic(stmts) -> None`. The SQL is mostly portable — we
    use ``%s`` placeholders for Postgres and translate to ``?`` for
    sqlite at the boundary.
    """

    def __init__(self, dsn: str):
        self.dsn = dsn
        self.is_pg = _is_postgres(dsn)
        self.is_sqlite = _is_sqlite(dsn)
        if not self.is_pg and not self.is_sqlite:
            raise RuntimeError(
                f"DATABASE_URL must be postgres:// or sqlite://, got: {dsn[:20]}..."
            )
        if self.is_pg:
            try:
                import psycopg2  # noqa: F401
                import psycopg2.extras  # noqa: F401
            except ImportError as exc:
                raise RuntimeError(
                    "psycopg2 is required for Postgres backend. "
                    "Install with: pip install psycopg2-binary"
                ) from exc

    def connect(self):
        if self.is_pg:
            import psycopg2
            import psycopg2.extras
            # Production: short-lived per-request connections. A real
            # deployment would use a pool (psycopg_pool or pgbouncer);
            # YAGNI for now — the shim's QPS is low (one inbound msg
            # per few seconds at peak).
            conn = psycopg2.connect(self.dsn, connect_timeout=5)
            conn.autocommit = False
            return conn
        # sqlite
        path = self.dsn[len("sqlite://"):] if self.dsn.startswith("sqlite://") else self.dsn
        conn = sqlite3.connect(path, timeout=5, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    def query(self, sql: str, params: tuple = ()) -> list[tuple]:
        sql_local = self._translate(sql)
        conn = self.connect()
        try:
            cur = conn.cursor()
            cur.execute(sql_local, params)
            rows = cur.fetchall()
            cur.close()
            return [tuple(r) for r in rows]
        finally:
            conn.close()

    def _translate(self, sql: str) -> str:
        # Translate %s placeholders to ? for sqlite. Postgres uses %s
        # natively. We don't translate dollar-quotes or ::uuid casts —
        # those only appear in psql heredocs (worker side), never here.
        if self.is_sqlite:
            return sql.replace("%s", "?")
        return sql

    def cursor_execute(self, cur, sql: str, params: tuple = ()) -> None:
        """Execute against a cursor with auto-translation of placeholders."""
        cur.execute(self._translate(sql), params)


db: DBBackend | None = None


def get_db() -> DBBackend:
    global db
    if db is None:
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL not set")
        db = DBBackend(DATABASE_URL)
    return db


# ─── Store-id lookup (cached) ─────────────────────────────────────────────

# brand "safiyafood" → stores.subscriber_id "safiyafood.jaringan-dagang.id"
# (cf. seller scripts/seed-from-buyer-catalog.py).
_BRAND_TO_SUBSCRIBER_SUFFIX = ".jaringan-dagang.id"

_store_cache: dict[str, tuple[str, str, float]] = {}
"""brand → (store_id, default_inbox_id, fetched_at_monotonic)."""
_store_cache_lock = threading.Lock()


def _brand_subscriber_id(brand: str) -> str:
    """Map a brand slug to a Beckn subscriber_id.

    The seller-repo convention is ``<slug>.jaringan-dagang.id`` (see
    ``scripts/seed-from-buyer-catalog.py`` BRAND_CATALOG). Until the
    storefront sends the canonical subscriber_id directly, we
    reconstruct it here.
    """
    brand = brand.strip().lower()
    if not brand:
        return ""
    return f"{brand}{_BRAND_TO_SUBSCRIBER_SUFFIX}"


def lookup_store_and_inbox(brand: str) -> tuple[str, str] | None:
    """Return (store_id, inbox_id) for a brand, or None if unknown.

    The inbox is the website inbox for the store (channel='website').
    If the store exists but has no website inbox, returns None — the
    operator must create one via the CRM API first
    (see docs/crm-bridge-contract.md §8).
    """
    now = time.monotonic()
    with _store_cache_lock:
        cached = _store_cache.get(brand)
        if cached and (now - cached[2]) < STORE_LOOKUP_TTL_SEC:
            return (cached[0], cached[1])

    subscriber_id = _brand_subscriber_id(brand)
    if not subscriber_id:
        return None

    backend = get_db()
    rows = backend.query(
        """
        SELECT s.id::text, i.id::text
        FROM stores s
        LEFT JOIN inboxes i
          ON i.store_id = s.id AND i.channel = 'website'
        WHERE s.subscriber_id = %s
        ORDER BY i.created_at NULLS LAST
        LIMIT 1;
        """ if backend.is_pg else
        # sqlite: no ::text, no NULLS LAST.
        """
        SELECT s.id, i.id
        FROM stores s
        LEFT JOIN inboxes i
          ON i.store_id = s.id AND i.channel = 'website'
        WHERE s.subscriber_id = %s
        ORDER BY i.created_at
        LIMIT 1;
        """,
        (subscriber_id,),
    )
    if not rows:
        return None
    store_id, inbox_id = rows[0]
    if not store_id or not inbox_id:
        return None
    with _store_cache_lock:
        _store_cache[brand] = (str(store_id), str(inbox_id), now)
    return (str(store_id), str(inbox_id))


# ─── Ingest ──────────────────────────────────────────────────────────────

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _valid_uuid(s: str | None) -> bool:
    return bool(s) and bool(_UUID_RE.match(s or ""))


def handle_ingest(body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Upsert contact + conversation + insert contact message.

    Returns (status_code, response_body). The response is JSON-encoded
    by the caller.
    """
    brand = (body.get("brand") or "").strip()
    customer_id = (body.get("customer_id") or "").strip()
    text = (body.get("text") or "").strip()
    conversation_id = (body.get("conversation_id") or "").strip() or None
    image_url = body.get("image_url") or None  # noqa: F841 — reserved for B6

    if not brand:
        return 400, {"error": "missing_brand"}
    if not customer_id:
        return 400, {"error": "missing_customer_id"}
    if not text:
        return 400, {"error": "empty_text"}
    if not _valid_uuid(customer_id):
        return 400, {"error": "bad_customer_id"}
    if conversation_id and not _valid_uuid(conversation_id):
        return 400, {"error": "bad_conversation_id"}

    lookup = lookup_store_and_inbox(brand)
    if not lookup:
        return 404, {"error": "unknown_brand", "brand": brand}
    store_id, inbox_id = lookup

    backend = get_db()
    conn = backend.connect()
    try:
        cur = conn.cursor()

        # ── Upsert contact ────────────────────────────────────────────
        contact_ext_id = f"web-{customer_id}"
        contact_id = _upsert_contact(cur, backend, store_id, contact_ext_id)

        # ── Upsert conversation ───────────────────────────────────────
        # external_id pattern (when client supplies a uuid we honour it
        # via that path; when they don't, we mint one and persist it).
        if conversation_id:
            conv_ext_id = f"web-{conversation_id}"
        else:
            conv_ext_id = f"web-{contact_ext_id}-{brand}"
        conv_id = _upsert_conversation(
            cur, backend,
            store_id=store_id,
            inbox_id=inbox_id,
            contact_id=contact_id,
            channel="website",
            external_id=conv_ext_id,
            preferred_id=conversation_id,
        )

        # ── Insert contact message ────────────────────────────────────
        msg_ext_id = f"web-msg-{uuid.uuid4().hex}"
        _insert_contact_message(
            cur, backend,
            conversation_id=conv_id,
            store_id=store_id,
            text=text,
            external_id=msg_ext_id,
        )

        # ── Maintain conversation.last_message_at / preview ───────────
        _bump_conversation_preview(
            cur, backend, conv_id=conv_id, preview=text[:280],
        )

        conn.commit()
        cur.close()
        return 200, {"conversation_id": conv_id}
    except Exception:
        conn.rollback()
        logger.exception("ingest failed brand=%s customer=%s", brand, customer_id[:8])
        return 503, {"error": "db_error"}
    finally:
        conn.close()


def _upsert_contact(cur, backend: DBBackend, store_id: str, ext_id: str) -> str:
    if backend.is_pg:
        backend.cursor_execute(cur,
            """
            INSERT INTO contacts (id, store_id, external_id, created_at, updated_at)
            VALUES (gen_random_uuid(), %s, %s, now(), now())
            ON CONFLICT (store_id, external_id) WHERE external_id IS NOT NULL
            DO UPDATE SET updated_at = now()
            RETURNING id::text;
            """,
            (store_id, ext_id),
        )
        return cur.fetchone()[0]
    # sqlite: no gen_random_uuid, no partial-index conflict target.
    backend.cursor_execute(cur,
        "SELECT id FROM contacts WHERE store_id = %s AND external_id = %s",
        (store_id, ext_id),
    )
    row = cur.fetchone()
    if row:
        return row[0] if isinstance(row, tuple) else row["id"]
    new_id = str(uuid.uuid4())
    backend.cursor_execute(cur,
        "INSERT INTO contacts (id, store_id, external_id, created_at, updated_at) "
        "VALUES (%s, %s, %s, datetime('now'), datetime('now'))",
        (new_id, store_id, ext_id),
    )
    return new_id


def _upsert_conversation(
    cur,
    backend: DBBackend,
    *,
    store_id: str,
    inbox_id: str,
    contact_id: str,
    channel: str,
    external_id: str,
    preferred_id: str | None,
) -> str:
    if backend.is_pg:
        # If preferred_id supplied, attempt INSERT-with-that-id; on
        # conflict (e.g. another tab on the same device), fall through
        # to the external_id-keyed upsert.
        if preferred_id:
            backend.cursor_execute(cur,
                """
                INSERT INTO conversations (
                  id, store_id, inbox_id, contact_id, channel, state,
                  external_id, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, 'bot_active', %s, now(), now())
                ON CONFLICT (id) DO NOTHING
                RETURNING id::text;
                """,
                (preferred_id, store_id, inbox_id, contact_id, channel, external_id),
            )
            row = cur.fetchone()
            if row:
                return row[0]
            # Fall through to fetch existing row by id.
            backend.cursor_execute(cur,
                "SELECT id::text FROM conversations WHERE id = %s",
                (preferred_id,),
            )
            row = cur.fetchone()
            if row:
                return row[0]
        # No preferred_id (or insert-by-id missed): UPSERT by external_id.
        backend.cursor_execute(cur,
            """
            INSERT INTO conversations (
              id, store_id, inbox_id, contact_id, channel, state,
              external_id, created_at, updated_at
            )
            VALUES (
              gen_random_uuid(), %s, %s, %s, %s, 'bot_active', %s,
              now(), now()
            )
            ON CONFLICT (store_id, external_id) WHERE external_id IS NOT NULL
            DO UPDATE SET updated_at = now()
            RETURNING id::text;
            """,
            (store_id, inbox_id, contact_id, channel, external_id),
        )
        return cur.fetchone()[0]
    # sqlite fallback
    if preferred_id:
        backend.cursor_execute(cur,
            "SELECT id FROM conversations WHERE id = %s", (preferred_id,),
        )
        row = cur.fetchone()
        if row:
            return row[0] if isinstance(row, tuple) else row["id"]
    backend.cursor_execute(cur,
        "SELECT id FROM conversations WHERE store_id = %s AND external_id = %s",
        (store_id, external_id),
    )
    row = cur.fetchone()
    if row:
        return row[0] if isinstance(row, tuple) else row["id"]
    new_id = preferred_id or str(uuid.uuid4())
    backend.cursor_execute(cur,
        "INSERT INTO conversations ("
        "  id, store_id, inbox_id, contact_id, channel, state, external_id,"
        "  created_at, updated_at"
        ") VALUES (%s, %s, %s, %s, %s, 'bot_active', %s, datetime('now'), datetime('now'))",
        (new_id, store_id, inbox_id, contact_id, channel, external_id),
    )
    return new_id


def _insert_contact_message(
    cur,
    backend: DBBackend,
    *,
    conversation_id: str,
    store_id: str,
    text: str,
    external_id: str,
) -> None:
    content = json.dumps({"text": text, "blocks": []})
    if backend.is_pg:
        backend.cursor_execute(cur,
            """
            INSERT INTO messages (
              id, conversation_id, store_id, sender, content, delivery,
              external_id, created_at, updated_at
            )
            VALUES (
              gen_random_uuid(), %s, %s, 'contact', %s::jsonb, 'na', %s,
              now(), now()
            )
            ON CONFLICT (conversation_id, external_id) WHERE external_id IS NOT NULL
            DO NOTHING;
            """,
            (conversation_id, store_id, content, external_id),
        )
        return
    new_id = str(uuid.uuid4())
    backend.cursor_execute(cur,
        "INSERT INTO messages ("
        "  id, conversation_id, store_id, sender, content, delivery,"
        "  external_id, created_at, updated_at"
        ") VALUES (%s, %s, %s, 'contact', %s, 'na', %s, datetime('now'), datetime('now'))",
        (new_id, conversation_id, store_id, content, external_id),
    )


def _bump_conversation_preview(
    cur, backend: DBBackend, *, conv_id: str, preview: str
) -> None:
    if backend.is_pg:
        backend.cursor_execute(cur,
            "UPDATE conversations SET last_message_at = now(), "
            "last_message_preview = %s WHERE id = %s",
            (preview, conv_id),
        )
        return
    backend.cursor_execute(cur,
        "UPDATE conversations SET last_message_at = datetime('now'), "
        "last_message_preview = %s WHERE id = %s",
        (preview, conv_id),
    )


# ─── Replies ──────────────────────────────────────────────────────────────

# CRM sender → wire sender. We translate at the boundary so the chat UI
# sees its own vocabulary (customer/bot/agent).
_SENDER_DB_TO_WIRE = {
    "contact": "customer",
    "bot": "bot",
    "agent": "agent",
}


def handle_replies(query: dict[str, list[str]]) -> tuple[int, dict[str, Any]]:
    conv_id = (query.get("conversation", [""])[0] or "").strip()
    after = (query.get("after", [""])[0] or "").strip() or None
    if not _valid_uuid(conv_id):
        return 400, {"error": "missing_conversation"}
    backend = get_db()
    # Cheap existence check — also returns 404 if the conversation
    # doesn't exist (not just "no messages").
    exists = backend.query(
        "SELECT 1 FROM conversations WHERE id = %s LIMIT 1",
        (conv_id,),
    )
    if not exists:
        return 404, {"error": "unknown_conversation"}

    if after:
        if not _valid_uuid(after):
            return 400, {"error": "bad_after"}
        if backend.is_pg:
            rows = backend.query(
                """
                SELECT id::text, conversation_id::text, store_id::text,
                       sender::text, content, created_at::text, delivery::text
                FROM messages
                WHERE conversation_id = %s
                  AND created_at > (
                    SELECT created_at FROM messages WHERE id = %s
                  )
                ORDER BY created_at ASC, id ASC
                LIMIT 200;
                """,
                (conv_id, after),
            )
        else:
            rows = backend.query(
                """
                SELECT id, conversation_id, store_id, sender, content,
                       created_at, delivery
                FROM messages
                WHERE conversation_id = %s
                  AND created_at > (
                    SELECT created_at FROM messages WHERE id = %s
                  )
                ORDER BY created_at ASC, id ASC
                LIMIT 200;
                """,
                (conv_id, after),
            )
    else:
        if backend.is_pg:
            rows = backend.query(
                "SELECT id::text, conversation_id::text, store_id::text, "
                "sender::text, content, created_at::text, delivery::text "
                "FROM messages WHERE conversation_id = %s "
                "ORDER BY created_at ASC, id ASC LIMIT 200",
                (conv_id,),
            )
        else:
            rows = backend.query(
                "SELECT id, conversation_id, store_id, sender, content, "
                "created_at, delivery FROM messages WHERE conversation_id = %s "
                "ORDER BY created_at ASC, id ASC LIMIT 200",
                (conv_id,),
            )

    messages: list[dict[str, Any]] = []
    for r in rows:
        mid, cid, sid, sender, content, created_at, delivery = r
        # content may be a dict (Postgres jsonb) or a str (sqlite).
        if isinstance(content, str):
            try:
                content_obj = json.loads(content)
            except (ValueError, TypeError):
                content_obj = {"text": str(content), "blocks": []}
        else:
            content_obj = content
        messages.append({
            "id": mid,
            "conversation_id": cid,
            "store_id": sid,
            "sender": _SENDER_DB_TO_WIRE.get(sender, sender),
            "content": content_obj,
            "created_at": created_at,
            "delivery": delivery,
        })
    return 200, {"messages": messages}


# ─── HTTP server ──────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    server_version = "jd-bot-bridge/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        # Pipe http.server's noisy default logger through our standard
        # logger so journalctl sees a single source.
        logger.info("%s - %s", self.address_string(), fmt % args)

    def _send_json(self, status: int, body: dict[str, Any]) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        # No CORS: this endpoint is server-to-server only (Vercel proxy
        # → bridge). The browser never touches it.
        self.end_headers()
        self.wfile.write(payload)

    def _auth_ok(self) -> bool:
        if not INGEST_TOKEN:
            return False
        h = self.headers.get("Authorization", "")
        return h == f"Bearer {INGEST_TOKEN}"

    # ── GET /health, /replies ─────────────────────────────────────────────
    def do_GET(self) -> None:  # noqa: N802 — stdlib convention
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send_json(200, {"ok": True, "service": "jd-bot-bridge"})
            return
        if parsed.path == "/replies":
            if not self._auth_ok():
                self._send_json(401, {"error": "unauthorized"})
                return
            qs = parse_qs(parsed.query or "", keep_blank_values=True)
            try:
                status, body = handle_replies(qs)
            except Exception:
                logger.exception("replies failed")
                self._send_json(503, {"error": "db_error"})
                return
            self._send_json(status, body)
            return
        self._send_json(404, {"error": "not_found"})

    # ── POST /ingest ──────────────────────────────────────────────────────
    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/ingest":
            self._send_json(404, {"error": "not_found"})
            return
        if not self._auth_ok():
            self._send_json(401, {"error": "unauthorized"})
            return
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0 or length > 1_000_000:  # 1 MB safety cap
            self._send_json(400, {"error": "bad_body"})
            return
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._send_json(400, {"error": "bad_json"})
            return
        if not isinstance(body, dict):
            self._send_json(400, {"error": "bad_body"})
            return
        try:
            status, resp = handle_ingest(body)
        except Exception:
            logger.exception("ingest failed")
            self._send_json(503, {"error": "db_error"})
            return
        self._send_json(status, resp)


def main() -> int:
    if not DATABASE_URL:
        logger.error("DATABASE_URL is required")
        return 1
    if not INGEST_TOKEN:
        logger.error("BRIDGE_INGEST_TOKEN is required")
        return 1
    try:
        get_db()  # warm — also validates the DSN
    except RuntimeError as exc:
        logger.error("DB init failed: %s", exc)
        return 1
    server = ThreadingHTTPServer((BIND_HOST, PORT), Handler)
    logger.info("listening on %s:%s", BIND_HOST, PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("shutting down")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
