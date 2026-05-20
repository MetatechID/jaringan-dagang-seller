"""Task A4 — idempotently add the ``payments.xendit_invoice_url`` column.

Why this script exists
----------------------
The seller has no Alembic in active use; new tables come up via
``Base.metadata.create_all(checkfirst=True)`` on first request (see
``app/api/admin.py``). That handles new *tables* but is a no-op for new
*columns* on an existing table. Per the prior A7 pattern
(``scripts/add-image-base-url-column.py``) we add columns via a one-shot
``ALTER TABLE ... ADD COLUMN IF NOT EXISTS``, which Postgres 9.6+ supports
and which is rerun-safe.

What it adds
------------
- ``payments.xendit_invoice_url`` (VARCHAR(1024)) — the Xendit hosted
  checkout URL (also serves as the QR landing page for QRIS). Surfaced to
  the BAP through Beckn ``/on_confirm`` so the buyer storefront can render
  the "Pay with QR" panel without scraping the Xendit response.

Behaviour
---------
Default = **dry-run**: prints the SQL it would execute. No DB connection
required, no env vars needed.

``--apply`` requires ``DATABASE_URL`` to be set and runs the ALTER.

Usage
-----

    # Dry run (safe, prints SQL):
    python scripts/add-payment-invoice-url-column.py

    # Actually apply against live DB:
    DATABASE_URL=postgresql+asyncpg://... \\
        python scripts/add-payment-invoice-url-column.py --apply
"""

from __future__ import annotations

import argparse
import os
import sys


ALTER_SQL = (
    "ALTER TABLE payments "
    "ADD COLUMN IF NOT EXISTS xendit_invoice_url VARCHAR(1024);"
)


def print_dry_run_sql() -> None:
    """Print the SQL that --apply would execute. Safe."""
    print("-- jaringan-dagang-seller / add-payment-invoice-url-column.py (dry-run)")
    print("-- Task A4 — idempotently add payments.xendit_invoice_url.")
    print()
    print("BEGIN;")
    print(ALTER_SQL)
    print("COMMIT;")
    print()
    print("-- Re-running is safe: ALTER gated by 'IF NOT EXISTS' (Postgres 9.6+).")


async def apply_migration(database_url: str) -> None:
    """Apply the ALTER."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(database_url)
    async with engine.begin() as conn:
        await conn.execute(text(ALTER_SQL))
    await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Idempotently add payments.xendit_invoice_url. Default is "
            "dry-run (print SQL only)."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Execute the ALTER against $DATABASE_URL. Without this flag, only SQL is printed.",
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

    print(f"Applying ALTER against {db_url[:40]}...")
    asyncio.run(apply_migration(db_url))
    print("done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
