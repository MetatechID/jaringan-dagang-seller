"""Task A7 — one-shot, idempotent ALTER to add ``stores.image_base_url``
and backfill the Safiya row to ``https://safiya.beliaman.com``.

Why this script exists
----------------------
The seller repo has no Alembic in active use. Table creation goes through
``Base.metadata.create_all(checkfirst=True)`` via ``POST /api/admin/migrate``
(see ``app/api/admin.py``). ``create_all`` is idempotent for *tables* but it
does NOT add new *columns* to an existing table, so a one-shot ALTER is
needed before the catalog builder's per-store ``image_base_url`` plumbing
(Task A7) becomes useful end-to-end on live Postgres.

Postgres supports ``ADD COLUMN IF NOT EXISTS`` since 9.6, which makes the
ALTER idempotent.

Behaviour
---------
Default = **dry-run**: prints the SQL it would execute and exits. No DB
connection, no env vars required.

``--apply`` requires ``DATABASE_URL`` to be set in the environment and runs
the ALTER + the Safiya-row backfill UPDATE.

The backfill UPDATE filters on the canonical Safiya ``subscriber_id``
(``safiyafood.jaringan-dagang.id``), so re-running after a successful run
is a no-op for the value (UPDATE writes the same string), and the ALTER is
guarded by ``IF NOT EXISTS``.

Usage
-----

    # Print the SQL only (safe; no DB connection)
    python scripts/add-image-base-url-column.py

    # Actually apply against live DB:
    DATABASE_URL=postgresql+asyncpg://... \\
        python scripts/add-image-base-url-column.py --apply
"""

from __future__ import annotations

import argparse
import os
import sys


SAFIYA_SUBSCRIBER_ID = "safiyafood.jaringan-dagang.id"
SAFIYA_IMAGE_BASE_URL = "https://safiya.beliaman.com"


# Postgres 9.6+ ``ADD COLUMN IF NOT EXISTS`` makes this re-runnable. We
# pick VARCHAR(512) to match ``Store.logo_url`` — same shape, same room
# for a future CDN-prefixed origin.
ALTER_SQL = (
    "ALTER TABLE stores "
    "ADD COLUMN IF NOT EXISTS image_base_url VARCHAR(512);"
)

# Idempotent backfill — sets Safiya's storefront origin so that the catalog
# builder starts emitting safiya.beliaman.com-rooted image URLs as soon as
# the migration script has rewritten the rows to relative form. The WHERE
# filters by canonical subscriber_id so re-running is a no-op for any other
# store and a write-same-value no-op for Safiya.
BACKFILL_SAFIYA_SQL = (
    f"UPDATE stores SET image_base_url = '{SAFIYA_IMAGE_BASE_URL}' "
    f"WHERE subscriber_id = '{SAFIYA_SUBSCRIBER_ID}';"
)


def print_dry_run_sql() -> None:
    """Print the SQL that --apply would execute. Safe."""
    print("-- jaringan-dagang-seller / add-image-base-url-column.py (dry-run)")
    print("-- Task A7 — idempotently add stores.image_base_url + backfill Safiya.")
    print()
    print("BEGIN;")
    print(ALTER_SQL)
    print(BACKFILL_SAFIYA_SQL)
    print("COMMIT;")
    print()
    print("-- Re-running is safe:")
    print("--   * ALTER is gated by 'IF NOT EXISTS' (Postgres 9.6+).")
    print("--   * UPDATE filters by canonical subscriber_id and writes a")
    print("--     fixed value, so it converges to a fixed point.")


async def apply_migration(database_url: str) -> int:
    """Apply the ALTER + Safiya backfill. Returns rows updated by the UPDATE.

    Lazy-imports sqlalchemy so the default dry-run mode needs no extra deps.
    """
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy import text

    engine = create_async_engine(database_url)
    rows_updated = 0
    async with engine.begin() as conn:
        await conn.execute(text(ALTER_SQL))
        result = await conn.execute(
            text(
                "UPDATE stores SET image_base_url = :url "
                "WHERE subscriber_id = :sid"
            ),
            {"url": SAFIYA_IMAGE_BASE_URL, "sid": SAFIYA_SUBSCRIBER_ID},
        )
        rows_updated = result.rowcount or 0
    await engine.dispose()
    return rows_updated


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Idempotently add stores.image_base_url and backfill the Safiya "
            "row to https://safiya.beliaman.com. Default is dry-run (print "
            "SQL only)."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Actually execute the ALTER + UPDATE against $DATABASE_URL. "
            "Without this flag, only the SQL is printed."
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

    print(f"Applying ALTER + Safiya backfill against {db_url[:40]}...")
    rows = asyncio.run(apply_migration(db_url))
    print(f"done. Safiya row(s) updated: {rows}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
