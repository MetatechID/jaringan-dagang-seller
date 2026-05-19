"""Task C1 — idempotently materialise the Chatwoot-style CRM tables.

Why this script exists
----------------------
The seller repo has no Alembic in active use. The normal path to create
new tables on Neon is ``POST /api/admin/migrate`` which calls
``Base.metadata.create_all(checkfirst=True)`` for every registered model
(see ``app/api/admin.py``). That works perfectly on a fresh DB and is
idempotent for whole tables.

This script does the same thing scoped to **just** the CRM tables, for
operators who'd rather run a one-shot migration outside the live API
process. Behaviour:

* Default = dry-run: prints the ``CREATE TYPE`` (Postgres enums) and
  ``CREATE TABLE`` / ``CREATE INDEX`` DDL that would be executed and
  exits. Safe — no DB connection, no env vars required.
* ``--apply`` requires ``DATABASE_URL`` and calls
  ``Base.metadata.create_all(bind=engine, tables=[…CRM tables…], checkfirst=True)``.
  ``checkfirst=True`` makes the call a no-op against an already-migrated DB.

Tables created (Task C1):
  * ``contacts``
  * ``inboxes``
  * ``conversations``
  * ``messages``
  * ``labels``
  * ``conversation_labels`` (many-to-many join)

Enums (Postgres ``CREATE TYPE``):
  * ``conv_channel``     (website | whatsapp)
  * ``conversation_state`` (bot_active | human_handoff | resolved)
  * ``message_sender``   (contact | bot | agent)
  * ``message_delivery`` (na | pending | sent | failed)

Caveat — the no-Alembic path
----------------------------
``create_all`` is idempotent for tables and CREATE TYPE, but it does NOT
add new *columns* to an already-existing table. If a future task extends
one of these tables, that change needs a separate ALTER script (see e.g.
``scripts/add-image-base-url-column.py``). This script is for the
first-time materialisation only.

Usage
-----

    # Print the DDL only (safe; no DB connection)
    python scripts/add-crm-tables.py

    # Apply against live DB:
    DATABASE_URL=postgresql+asyncpg://...  python scripts/add-crm-tables.py --apply
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Make ``app.models`` importable when run from the scripts/ dir directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# Tables this script materialises. Order matters for human-readable dry-run
# output — parents before children.
CRM_TABLES: tuple[str, ...] = (
    "contacts",
    "inboxes",
    "conversations",
    "messages",
    "labels",
    "conversation_labels",
)

# Postgres enum types the schema introduces.
CRM_ENUM_TYPES: tuple[str, ...] = (
    "conv_channel",
    "conversation_state",
    "message_sender",
    "message_delivery",
)


def _crm_metadata_subset():
    """Return ``(metadata, [Table objects for CRM])``.

    Importing ``app.models`` triggers registration of every model so
    ``Base.metadata`` is fully populated; we then pick out the CRM tables.
    """
    import app.models  # noqa: F401 — side-effect: registers all models
    from app.models import Base

    tables = [Base.metadata.tables[name] for name in CRM_TABLES]
    return Base.metadata, tables


def _compile_ddl_for(metadata, tables) -> str:
    """Render the CREATE TYPE + CREATE TABLE + CREATE INDEX DDL for the
    CRM subset against the Postgres dialect.

    Uses SQLAlchemy's ``MockConnection`` so no real DB connection is made.
    """
    from io import StringIO

    from sqlalchemy import create_mock_engine
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateIndex, CreateTable

    # Render every Postgres ENUM type first (CREATE TYPE …).
    out = StringIO()

    dialect = postgresql.dialect()

    rendered_types: set[str] = set()
    for t in tables:
        for col in t.columns:
            # SAEnum's Postgres-side type carries .name; we render CREATE TYPE
            # for each distinct enum, once.
            ct = getattr(col.type, "name", None)
            from sqlalchemy import Enum as SAEnum

            if isinstance(col.type, SAEnum) and ct and ct not in rendered_types:
                rendered_types.add(ct)
                vals = ", ".join(
                    f"'{v.value if hasattr(v, 'value') else v}'"
                    for v in col.type.enums
                )
                out.write(f"CREATE TYPE {ct} AS ENUM ({vals});\n")

    # Then CREATE TABLE for each, in declared order.
    for t in tables:
        out.write(str(CreateTable(t).compile(dialect=dialect)).strip())
        out.write(";\n")

    # Then CREATE INDEX for each non-PK index (partial indexes included).
    for t in tables:
        for ix in t.indexes:
            out.write(str(CreateIndex(ix).compile(dialect=dialect)).strip())
            out.write(";\n")

    return out.getvalue()


def print_dry_run_sql() -> None:
    """Print the DDL that ``--apply`` would execute. Safe."""
    metadata, tables = _crm_metadata_subset()
    ddl = _compile_ddl_for(metadata, tables)

    print("-- jaringan-dagang-seller / add-crm-tables.py (dry-run)")
    print("-- Task C1 — Chatwoot-style CRM schema (contacts, inboxes,")
    print("-- conversations, messages, labels, conversation_labels).")
    print()
    print(f"-- Enums created: {', '.join(CRM_ENUM_TYPES)}")
    print(f"-- Tables created: {', '.join(CRM_TABLES)}")
    print()
    print("BEGIN;")
    print(ddl.rstrip())
    print("COMMIT;")
    print()
    print("-- Re-running --apply against an already-migrated DB is a no-op:")
    print("--   Base.metadata.create_all(..., checkfirst=True) skips existing")
    print("--   tables, and CREATE TYPE collisions are caught by the same flag.")


async def apply_migration(database_url: str) -> list[str]:
    """Create the CRM tables on the target DB. Returns the table names that
    are now present in the schema (post-create).

    Lazy-imports SQLAlchemy so dry-run mode never needs it.
    """
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy.ext.asyncio import create_async_engine

    metadata, tables = _crm_metadata_subset()
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as conn:

            def _create(sync_conn):
                metadata.create_all(
                    sync_conn, tables=tables, checkfirst=True
                )

            await conn.run_sync(_create)

        async with engine.begin() as conn:

            def _list(sync_conn):
                return sa_inspect(sync_conn).get_table_names()

            names = await conn.run_sync(_list)
    finally:
        await engine.dispose()
    return [n for n in names if n in CRM_TABLES]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Idempotently materialise the Chatwoot-style CRM tables "
            "(contacts, inboxes, conversations, messages, labels, "
            "conversation_labels) on the configured Postgres. Default is "
            "dry-run (print DDL only)."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Actually run Base.metadata.create_all(checkfirst=True) for the "
            "CRM subset against $DATABASE_URL. Without this flag, only the "
            "DDL is printed."
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

    print(f"Applying CRM schema migration against {db_url[:40]}...")
    present = asyncio.run(apply_migration(db_url))
    print(
        f"done. CRM tables now present on target DB: "
        f"{', '.join(present) if present else '(none)'}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
