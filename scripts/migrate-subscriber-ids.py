"""Task A3 — idempotent migration of legacy ``bpp.*.local`` subscriber ids
in ``stores.subscriber_id`` to the canonical ``<slug>.jaringan-dagang.id``
form.

Live seller Postgres (Neon) state (verified via GET /api/stores):
  - safiyafood.jaringan-dagang.id        (already canonical)
  - matchamu.jaringan-dagang.id          (already canonical)
  - optimumnutrition.jaringan-dagang.id  (already canonical)
  - bpp.antarestar.local                 -> antarestar.jaringan-dagang.id
  - bpp.gendes.local                     -> gendes.jaringan-dagang.id
  - bpp.yourbrand.local                  -> yourbrand.jaringan-dagang.id

Default behaviour is **dry-run**: prints the SQL it would execute and
exits. Pass ``--apply`` AND set ``DATABASE_URL`` to actually run the
update against the configured Postgres.

Idempotent: each UPDATE has ``WHERE subscriber_id = '<legacy>'``, so
re-running after a successful migration becomes a no-op (0 rows match).

Usage:
    # Print the SQL only (safe; no DB connection)
    python scripts/migrate-subscriber-ids.py

    # Actually apply against live DB:
    DATABASE_URL=postgresql+asyncpg://... \\
        python scripts/migrate-subscriber-ids.py --apply
"""

from __future__ import annotations

import argparse
import os
import sys


# Map of legacy -> canonical subscriber_id. Add new rows here if more
# legacy ids are discovered; the script ignores any not present in the DB.
LEGACY_TO_CANONICAL: dict[str, str] = {
    "bpp.antarestar.local": "antarestar.jaringan-dagang.id",
    "bpp.gendes.local": "gendes.jaringan-dagang.id",
    "bpp.yourbrand.local": "yourbrand.jaringan-dagang.id",
}


def _sql_for(legacy: str, canonical: str) -> str:
    # Single quotes are safe here because every value in
    # LEGACY_TO_CANONICAL is a hardcoded constant; no user input.
    return (
        f"UPDATE stores SET subscriber_id = '{canonical}' "
        f"WHERE subscriber_id = '{legacy}';"
    )


def print_dry_run_sql() -> None:
    """Print the UPDATE statements that would be executed.

    Safe — no DB connection, no env vars required."""
    print("-- jaringan-dagang-seller / migrate-subscriber-ids.py (dry-run)")
    print(f"-- {len(LEGACY_TO_CANONICAL)} legacy subscriber_id(s) to migrate:")
    for legacy, canonical in LEGACY_TO_CANONICAL.items():
        print(f"--   {legacy}  ->  {canonical}")
    print()
    print("BEGIN;")
    for legacy, canonical in LEGACY_TO_CANONICAL.items():
        print(_sql_for(legacy, canonical))
    print("COMMIT;")
    print()
    print("-- Re-running is a no-op once applied: each UPDATE filters on the")
    print("-- legacy subscriber_id which by then no longer matches any row.")


async def apply_migration(database_url: str) -> int:
    """Apply the migration. Returns the total number of rows updated.

    Imports asyncpg / sqlalchemy lazily so dry-run mode never needs them.
    """
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy import text

    engine = create_async_engine(database_url)
    total = 0
    async with engine.begin() as conn:
        for legacy, canonical in LEGACY_TO_CANONICAL.items():
            result = await conn.execute(
                text(
                    "UPDATE stores SET subscriber_id = :canonical "
                    "WHERE subscriber_id = :legacy"
                ),
                {"canonical": canonical, "legacy": legacy},
            )
            n = result.rowcount or 0
            total += n
            print(f"  {legacy} -> {canonical}: {n} row(s) updated")
    await engine.dispose()
    return total


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Migrate legacy bpp.*.local subscriber_id values in the "
            "stores table to the canonical *.jaringan-dagang.id scheme. "
            "Default is dry-run (print SQL only)."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Actually execute the UPDATE against $DATABASE_URL. Without "
            "this flag, only the SQL is printed."
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

    print(f"Applying migration against {db_url[:40]}...")
    total = asyncio.run(apply_migration(db_url))
    print(f"done. {total} row(s) updated across {len(LEGACY_TO_CANONICAL)} legacy id(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
