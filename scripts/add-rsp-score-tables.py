"""Task A6 — idempotently create ``settlement_ledger`` + ``score_snapshots`` tables.

Why this script exists
----------------------
Task A6 ("ONDC RSP + Score, narrow") adds two new BPP-side tables:

- ``settlement_ledger`` — one row per order, recording the BPP-side
  payable amount, basis (DELIVERY / PICKUP / RECEIPT), window (P1D /
  P3D / P7D), status (NOT_PAID / PAID / PARTIAL_PAID), and an
  operator-supplied reference.
- ``score_snapshots`` — daily-rolled-up reputation metrics per store
  (completion_rate, return_rate, rating_avg, band).

The seller repo has no Alembic in active use; table creation goes
through ``Base.metadata.create_all(checkfirst=True)`` via
``POST /api/admin/migrate``. ``create_all`` does pick these tables up
automatically — but to allow operators to migrate without enabling the
admin endpoint, this script DDLs both tables explicitly and idempotently.

Postgres supports ``CREATE TABLE IF NOT EXISTS``; the enum types are
created via ``DO $$ ... CREATE TYPE ... EXCEPTION WHEN duplicate_object``
blocks so re-running is safe.

Behaviour
---------
Default = **dry-run**: prints the SQL it would execute. No DB connection
needed, no env vars required.

``--apply`` requires ``DATABASE_URL`` and runs the DDL.

Usage
-----

    # Dry run (safe, prints SQL):
    python scripts/add-rsp-score-tables.py

    # Actually apply against live DB:
    DATABASE_URL=postgresql+asyncpg://... \\
        python scripts/add-rsp-score-tables.py --apply
"""

from __future__ import annotations

import argparse
import os
import sys


# Enum types must exist before the CREATE TABLE statements reference them.
# Wrap each in a DO block so re-running is a no-op.
CREATE_TYPE_SETTLEMENT_BASIS = """
DO $$ BEGIN
    CREATE TYPE settlement_basis AS ENUM ('DELIVERY', 'PICKUP', 'RECEIPT');
EXCEPTION WHEN duplicate_object THEN null;
END $$;
"""

CREATE_TYPE_SETTLEMENT_WINDOW = """
DO $$ BEGIN
    CREATE TYPE settlement_window AS ENUM ('P1D', 'P3D', 'P7D');
EXCEPTION WHEN duplicate_object THEN null;
END $$;
"""

CREATE_TYPE_SETTLEMENT_STATUS = """
DO $$ BEGIN
    CREATE TYPE settlement_status AS ENUM ('NOT_PAID', 'PAID', 'PARTIAL_PAID');
EXCEPTION WHEN duplicate_object THEN null;
END $$;
"""

CREATE_TABLE_SETTLEMENT_LEDGER = """
CREATE TABLE IF NOT EXISTS settlement_ledger (
    id UUID PRIMARY KEY,
    order_id UUID NOT NULL UNIQUE REFERENCES orders(id) ON DELETE CASCADE,
    payment_id UUID REFERENCES payments(id) ON DELETE SET NULL,
    payable_amount BIGINT NOT NULL,
    settlement_basis settlement_basis NOT NULL DEFAULT 'DELIVERY',
    settlement_window settlement_window NOT NULL DEFAULT 'P1D',
    settlement_status settlement_status NOT NULL DEFAULT 'NOT_PAID',
    settlement_reference VARCHAR(255),
    settled_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);
"""

CREATE_INDEX_SETTLEMENT_LEDGER_STATUS = """
CREATE INDEX IF NOT EXISTS ix_settlement_ledger_status
ON settlement_ledger (settlement_status);
"""

CREATE_INDEX_SETTLEMENT_LEDGER_PAYMENT = """
CREATE INDEX IF NOT EXISTS ix_settlement_ledger_payment_id
ON settlement_ledger (payment_id);
"""

CREATE_TABLE_SCORE_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS score_snapshots (
    id UUID PRIMARY KEY,
    store_id UUID NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    period_start TIMESTAMP WITH TIME ZONE NOT NULL,
    period_end TIMESTAMP WITH TIME ZONE NOT NULL,
    completion_rate NUMERIC(5, 4) NOT NULL DEFAULT 0.0,
    return_rate NUMERIC(5, 4) NOT NULL DEFAULT 0.0,
    avg_response_hours NUMERIC(8, 2),
    resolution_time_hours NUMERIC(8, 2),
    rating_avg NUMERIC(3, 2) NOT NULL DEFAULT 0.0,
    band VARCHAR(16) NOT NULL DEFAULT 'POOR',
    total_orders INTEGER NOT NULL DEFAULT 0,
    completed_orders INTEGER NOT NULL DEFAULT 0,
    refunded_orders INTEGER NOT NULL DEFAULT 0,
    last_computed_at TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    CONSTRAINT uq_score_snapshots_store_period UNIQUE (store_id, period_start)
);
"""

CREATE_INDEX_SCORE_SNAPSHOTS_BAND = """
CREATE INDEX IF NOT EXISTS ix_score_snapshots_store_band
ON score_snapshots (store_id, band);
"""

CREATE_INDEX_SCORE_SNAPSHOTS_STORE = """
CREATE INDEX IF NOT EXISTS ix_score_snapshots_store_id
ON score_snapshots (store_id);
"""

DDL_STATEMENTS: list[str] = [
    CREATE_TYPE_SETTLEMENT_BASIS,
    CREATE_TYPE_SETTLEMENT_WINDOW,
    CREATE_TYPE_SETTLEMENT_STATUS,
    CREATE_TABLE_SETTLEMENT_LEDGER,
    CREATE_INDEX_SETTLEMENT_LEDGER_STATUS,
    CREATE_INDEX_SETTLEMENT_LEDGER_PAYMENT,
    CREATE_TABLE_SCORE_SNAPSHOTS,
    CREATE_INDEX_SCORE_SNAPSHOTS_BAND,
    CREATE_INDEX_SCORE_SNAPSHOTS_STORE,
]


def print_dry_run_sql() -> None:
    """Print the SQL that --apply would execute. Safe."""
    print("-- jaringan-dagang-seller / add-rsp-score-tables.py (dry-run)")
    print("-- Task A6 — idempotently create settlement_ledger + score_snapshots.")
    print()
    print("BEGIN;")
    for stmt in DDL_STATEMENTS:
        s = stmt.strip()
        if s:
            print(s)
    print("COMMIT;")
    print()
    print("-- Re-running is safe:")
    print("--   * CREATE TYPE is wrapped in DO ... EXCEPTION duplicate_object.")
    print("--   * CREATE TABLE / INDEX use 'IF NOT EXISTS'.")


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
            "Idempotently create settlement_ledger + score_snapshots "
            "tables. Default is dry-run (print SQL only)."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Execute the DDL against $DATABASE_URL. Without this flag, "
            "only SQL is printed."
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
        f"Applying settlement_ledger + score_snapshots DDL against {db_url[:40]}..."
    )
    count = asyncio.run(apply_migration(db_url))
    print(f"done. statements executed: {count}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
