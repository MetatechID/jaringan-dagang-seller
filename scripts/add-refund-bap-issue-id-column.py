"""Task A6 — promote ``RefundRequest.bap_issue_id`` to a dedicated column.

Why this script exists
----------------------
Task A5 ("ONDC IGM, narrow") shipped the /issue -> RefundRequest path
with the BAP-issued Issue id stashed inside ``seller_note`` as
``bap_issue_id=<uuid>``. The A5 self-review flagged that overload as a
prerequisite to clean up before A6 added more state.

A6 promotes ``bap_issue_id`` to a first-class indexed column on
``refund_requests``. This script is the one-shot migration:

  1. ``ALTER TABLE refund_requests ADD COLUMN IF NOT EXISTS
     bap_issue_id VARCHAR(64);`` (Postgres 9.6+).
  2. ``CREATE INDEX IF NOT EXISTS ix_refund_requests_bap_issue_id ON
     refund_requests (bap_issue_id);`` for the /on_issue reconcile path.
  3. Back-fill from the seller_note stash:
     ``UPDATE refund_requests
        SET bap_issue_id = SUBSTRING(seller_note FROM 'bap_issue_id=([0-9a-f-]+)')
      WHERE bap_issue_id IS NULL AND seller_note LIKE 'bap_issue_id=%';``

Re-running is safe: ALTER + CREATE INDEX both use ``IF NOT EXISTS``,
and the UPDATE filters on ``bap_issue_id IS NULL`` so converged rows
are skipped.

Behaviour
---------
Default = **dry-run**: prints the SQL it would execute. No DB connection
needed, no env vars required.

``--apply`` requires ``DATABASE_URL`` and runs the DDL + back-fill.

Usage
-----

    # Dry run (safe, prints SQL):
    python scripts/add-refund-bap-issue-id-column.py

    # Actually apply against live DB:
    DATABASE_URL=postgresql+asyncpg://... \\
        python scripts/add-refund-bap-issue-id-column.py --apply
"""

from __future__ import annotations

import argparse
import os
import sys


ALTER_SQL = (
    "ALTER TABLE refund_requests "
    "ADD COLUMN IF NOT EXISTS bap_issue_id VARCHAR(64);"
)

CREATE_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS ix_refund_requests_bap_issue_id "
    "ON refund_requests (bap_issue_id);"
)

# Back-fill from the seller_note overload. Postgres SUBSTRING ... FROM
# pattern captures the UUID portion of the ``bap_issue_id=<uuid>`` stash.
# WHERE filters skip already-converged rows so re-running is a no-op.
BACKFILL_SQL = (
    "UPDATE refund_requests "
    "SET bap_issue_id = SUBSTRING(seller_note FROM 'bap_issue_id=([0-9a-fA-F\\-]+)') "
    "WHERE bap_issue_id IS NULL "
    "AND seller_note LIKE 'bap_issue_id=%';"
)

DDL_STATEMENTS: list[str] = [
    ALTER_SQL,
    CREATE_INDEX_SQL,
    BACKFILL_SQL,
]


def print_dry_run_sql() -> None:
    """Print the SQL that --apply would execute. Safe."""
    print("-- jaringan-dagang-seller / add-refund-bap-issue-id-column.py (dry-run)")
    print("-- Task A6 — promote RefundRequest.bap_issue_id to a dedicated indexed column.")
    print()
    print("BEGIN;")
    for stmt in DDL_STATEMENTS:
        s = stmt.strip()
        if s:
            print(s)
    print("COMMIT;")
    print()
    print("-- Re-running is safe:")
    print("--   * ALTER uses 'ADD COLUMN IF NOT EXISTS'.")
    print("--   * CREATE INDEX uses 'IF NOT EXISTS'.")
    print("--   * UPDATE skips rows where bap_issue_id is already populated.")


async def apply_migration(database_url: str) -> int:
    """Run all DDL statements transactionally. Returns # of statements run."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(database_url)
    count = 0
    async with engine.begin() as conn:
        for stmt in DDL_STATEMENTS:
            s = stmt.strip()
            if not s:
                continue
            await conn.execute(text(s))
            count += 1
    await engine.dispose()
    return count


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Idempotently add refund_requests.bap_issue_id + index + "
            "back-fill from the seller_note overload. Default is dry-run "
            "(print SQL only)."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Execute the DDL + back-fill against $DATABASE_URL. Without "
            "this flag, only SQL is printed."
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

    print(f"Applying refund_requests.bap_issue_id DDL + back-fill against {db_url[:40]}...")
    count = asyncio.run(apply_migration(db_url))
    print(f"done. statements executed: {count}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
