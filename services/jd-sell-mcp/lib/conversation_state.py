"""SQLite-backed per-conversation state for the MCP server.

The chatbot (B4) passes a stable ``conversation_id`` (UUID-shaped string) on
every tool call. The MCP server remembers, per conversation:

  * the active search session_id + bpp_id/bpp_uri (so cart_add can target the
    right BPP without the bot having to re-pass it)
  * the active cart_id + transaction_id (so cart_view/start_checkout/
    payment_status can act without it)
  * the last billing/shipping payload (handy for diagnostic logging only —
    we re-send these on every /init call regardless)

SQLite is sufficient: the bot is single-VM, single-process, and total volume
is on the order of one row per active chat. We use ``WAL`` journal mode so
the FastAPI app's many small concurrent reads/writes don't lock each other
out.

We do not use sqlalchemy here. Direct ``sqlite3`` keeps the dep-count down
and the code obvious. All access is synchronous, wrapped in a tiny lock so
two concurrent tool calls on the same row can't tear writes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
from typing import Any

logger = logging.getLogger(__name__)


DEFAULT_DB_PATH = "/var/lib/jd-sell-mcp/state.db"
FALLBACK_DB_PATH = "/tmp/jd-sell-mcp.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversation_state (
  conversation_id  TEXT PRIMARY KEY,
  session_id       TEXT,
  cart_id          TEXT,
  transaction_id   TEXT,
  bpp_id           TEXT,
  bpp_uri          TEXT,
  billing_json     TEXT,
  shipping_json    TEXT,
  updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def _resolve_db_path(requested: str | None = None) -> str:
    """Pick a usable path. Try requested → default → fallback in that order.

    Raises OSError if all three are unwritable, which would only happen in
    a wildly mis-provisioned container — let it fail loudly at startup.
    """
    candidates: list[str] = []
    if requested:
        candidates.append(requested)
    candidates.extend([DEFAULT_DB_PATH, FALLBACK_DB_PATH])

    for path in candidates:
        try:
            parent = os.path.dirname(path) or "."
            os.makedirs(parent, exist_ok=True)
            # Touch it to confirm writeability.
            with open(path, "a"):
                pass
            return path
        except OSError as exc:
            logger.info("state path %s not usable (%s); trying next", path, exc)
            continue

    raise OSError(
        f"None of the candidate paths are writable: {candidates}. "
        "Set STATE_DB_PATH to a path you control."
    )


class ConversationStateStore:
    """Per-conversation MCP state, persisted to SQLite."""

    def __init__(self, db_path: str | None = None) -> None:
        env_path = os.environ.get("STATE_DB_PATH") or db_path
        self._db_path = _resolve_db_path(env_path)
        # asyncio.Lock — the sqlite3 stdlib is thread-safe in our usage
        # pattern, but a tool may issue multiple read-modify-write turns
        # for the same conversation back-to-back and we don't want a torn
        # second write to lose part of the first.
        self._lock = asyncio.Lock()
        self._init_schema()
        logger.info("ConversationStateStore using %s", self._db_path)

    @property
    def db_path(self) -> str:
        return self._db_path

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, isolation_level=None)
        # WAL = more concurrent readers + writers; the journal is on the
        # filesystem, so this also survives process restarts.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    # ---------- Public API ----------

    async def get(self, conversation_id: str) -> dict[str, Any] | None:
        async with self._lock:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT * FROM conversation_state WHERE conversation_id = ?",
                    (conversation_id,),
                ).fetchone()
        if row is None:
            return None
        return _row_to_dict(row)

    async def upsert(
        self,
        conversation_id: str,
        *,
        session_id: str | None = None,
        cart_id: str | None = None,
        transaction_id: str | None = None,
        bpp_id: str | None = None,
        bpp_uri: str | None = None,
        billing: dict[str, Any] | None = None,
        shipping: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Merge non-None fields into the row; create if missing."""
        async with self._lock:
            with self._conn() as conn:
                existing = conn.execute(
                    "SELECT * FROM conversation_state WHERE conversation_id = ?",
                    (conversation_id,),
                ).fetchone()
                fields = {
                    "session_id": session_id,
                    "cart_id": cart_id,
                    "transaction_id": transaction_id,
                    "bpp_id": bpp_id,
                    "bpp_uri": bpp_uri,
                    "billing_json": json.dumps(billing) if billing is not None else None,
                    "shipping_json": json.dumps(shipping) if shipping is not None else None,
                }
                if existing is None:
                    cols = ["conversation_id"] + list(fields.keys())
                    values = [conversation_id] + [fields[k] for k in fields]
                    placeholders = ",".join(["?"] * len(cols))
                    conn.execute(
                        f"INSERT INTO conversation_state ({','.join(cols)}) "
                        f"VALUES ({placeholders})",
                        values,
                    )
                else:
                    sets = []
                    values_for_update: list[Any] = []
                    for col, val in fields.items():
                        if val is not None:
                            sets.append(f"{col} = ?")
                            values_for_update.append(val)
                    sets.append("updated_at = CURRENT_TIMESTAMP")
                    if sets:
                        values_for_update.append(conversation_id)
                        conn.execute(
                            "UPDATE conversation_state "
                            f"SET {','.join(sets)} "
                            "WHERE conversation_id = ?",
                            values_for_update,
                        )
                row = conn.execute(
                    "SELECT * FROM conversation_state WHERE conversation_id = ?",
                    (conversation_id,),
                ).fetchone()
        assert row is not None
        return _row_to_dict(row)

    async def delete(self, conversation_id: str) -> bool:
        async with self._lock:
            with self._conn() as conn:
                cur = conn.execute(
                    "DELETE FROM conversation_state WHERE conversation_id = ?",
                    (conversation_id,),
                )
                return (cur.rowcount or 0) > 0


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d: dict[str, Any] = dict(row)
    for blob_key in ("billing_json", "shipping_json"):
        raw = d.get(blob_key)
        if raw:
            try:
                d[blob_key.removesuffix("_json")] = json.loads(raw)
            except json.JSONDecodeError:
                d[blob_key.removesuffix("_json")] = None
        else:
            d[blob_key.removesuffix("_json")] = None
    return d
