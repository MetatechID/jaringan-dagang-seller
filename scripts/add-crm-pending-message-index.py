"""Task C4 — idempotently add the bridge-poll-friendly composite index on
``messages(sender, delivery, created_at)``.

Why this script exists
----------------------
The seller repo has no Alembic in active use. Table creation goes through
``Base.metadata.create_all(checkfirst=True)`` via ``POST /api/admin/migrate``
(see ``app/api/admin.py``). ``create_all`` is idempotent for *tables* and
*indexes declared on tables it creates*, but it does NOT add a new index
to an already-existing table on its own — operators need a one-shot
``CREATE INDEX IF NOT EXISTS`` against the live DB.

This script materialises the C4 composite index that supports the bot
bridge's hot polling loop::

    SELECT id, conversation_id, content
    FROM messages
    WHERE sender = 'agent' AND delivery = 'pending'
    ORDER BY created_at
    FOR UPDATE SKIP LOCKED
    LIMIT N;

The pre-existing ``ix_messages_delivery`` (column-level index added in C1)
covers single-column scans; the C4 index covers the bridge's
two-enum-predicate + ORDER BY in one btree so it stays fast as non-pending
agent messages accumulate.

Postgres supports ``CREATE INDEX IF NOT EXISTS`` since 9.5, which makes
this DDL idempotent.

Behaviour
---------
Default = **dry-run**: prints the SQL it would execute and exits. Safe;
no DB connection, no env vars required.

``--apply`` requires ``DATABASE_URL`` to be set in the environment and
runs the ``CREATE INDEX IF NOT EXISTS``.

Usage
-----

    # Print the SQL only (safe; no DB connection)
    python scripts/add-crm-pending-message-index.py

    # Actually apply against live DB:
    DATABASE_URL=postgresql+asyncpg://... \\
        python scripts/add-crm-pending-message-index.py --apply
"""

from __future__ import annotations

import argparse
import os
import sys


INDEX_NAME = "ix_messages_sender_delivery_created_at"

# CREATE INDEX IF NOT EXISTS (Postgres 9.5+) makes this re-runnable. The
# column order matches the SQLAlchemy ``Index(...)`` declaration at the
# bottom of ``app/models/conversation.py``.
CREATE_INDEX_SQL = (
    f"CREATE INDEX IF NOT EXISTS {INDEX_NAME} "
    "ON messages (sender, delivery, created_at);"
)


def print_dry_run_sql() -> None:
    """Print the SQL that --apply would execute. Safe."""
    print(
        "-- jaringan-dagang-seller / add-crm-pending-message-index.py (dry-run)"
    )
    print(
        "-- Task C4 — idempotently add the bridge-poll-friendly composite"
    )
    print("-- index on messages(sender, delivery, created_at).")
    print()
    print("BEGIN;")
    print(CREATE_INDEX_SQL)
    print("COMMIT;")
    print()
    print("-- Re-running is safe: 'IF NOT EXISTS' (Postgres 9.5+) skips when")
    print("-- the index is already present.")


async def apply_migration(database_url: str) -> bool:
    """Apply the CREATE INDEX. Returns True if the index is present on the
    target DB after the call (whether we created it or it was already there).

    Lazy-imports sqlalchemy so dry-run mode never needs it.
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(CREATE_INDEX_SQL))

        async with engine.begin() as conn:
            # pg_indexes is the standard catalog view; we check presence
            # without depending on the SQLAlchemy reflection layer.
            result = await conn.execute(
                text(
                    "SELECT 1 FROM pg_indexes "
                    "WHERE schemaname = current_schema() "
                    "AND tablename = 'messages' "
                    "AND indexname = :name"
                ),
                {"name": INDEX_NAME},
            )
            present = result.scalar_one_or_none() is not None
    finally:
        await engine.dispose()
    return present


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Idempotently add the bridge-poll-friendly composite index "
            "on messages(sender, delivery, created_at). Default is "
            "dry-run (print SQL only)."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Actually execute CREATE INDEX IF NOT EXISTS against "
            "$DATABASE_URL. Without this flag, only the SQL is printed."
        ),
    )
    args = parser.parse_args()

    if not args.apply:
        print_dry_run_sql()
        return 0

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print(
            "ERROR: --apply requires DATABASE_URL to be set in the environment.",
            file=sys.stderr,
        )
        return 2

    import asyncio

    print(
        f"Applying CREATE INDEX IF NOT EXISTS {INDEX_NAME} against "
        f"{db_url[:40]}..."
    )
    present = asyncio.run(apply_migration(db_url))
    print(
        f"done. {INDEX_NAME} present on target DB: "
        f"{'yes' if present else 'NO (unexpected — check logs)'}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
