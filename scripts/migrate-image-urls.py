"""Task A7 — idempotent migration of legacy absolute image URLs in
``product_images`` / ``sku_images`` to host-agnostic relative paths.

Why this script exists
----------------------
The live seller catalog (Neon Postgres, surfaced via
``https://jaringan-dagang-seller-api.metatech.id/api/products``) stores
image URLs like::

    https://partner-demos.jaringan-dagang.metatech.id/brands/safiyafood/products/<file>.svg

That host is **DEAD** (ECONNREFUSED). The buyer storefront
``safiya.beliaman.com`` serves the same SVGs from same-origin relative
paths and is fine, but the Beckn-emitted ``Item.images[].url`` (read by
the nullclaw bot and any other BAP) points at the dead host -> broken
image links for buyers.

The fix (Option A — minimal-data-change, multi-tenant-correct): store
relative paths in the DB, prepend a per-store ``image_base_url`` at the
moment Beckn ``Item.images[].url`` is constructed (handled by
``app/beckn/catalog_builder.py``'s ``_resolve_image_url``). This script
rewrites the existing legacy absolute URLs to relative form so the new
resolver does the right thing.

Default = **dry-run**: prints the SQL it would execute and exits. No DB
connection, no env vars required.

``--apply`` requires ``DATABASE_URL`` and runs the rewrites.

``--prune-test-artifacts`` (off by default) additionally deletes the
SAF-SYNC test product row (and its cascaded images/SKUs). Required to
avoid mass-delete-by-accident.

Live audit snapshot (captured during Task A7):
  * 17 products in Safiya catalog
  * 73 ``product_images`` rows + 36 ``sku_images`` rows = 109 image rows
  * 108 carry the dead ``partner-demos.jaringan-dagang.metatech.id`` host
  * 1 carries ``https://example.com/sync-test.svg`` (the SAF-SYNC artifact)
  * 0 relative paths today

Usage
-----

    # Print the SQL only (safe; no DB connection)
    python scripts/migrate-image-urls.py

    # Print SQL including the optional SAF-SYNC delete
    python scripts/migrate-image-urls.py --prune-test-artifacts

    # Actually apply against live DB:
    DATABASE_URL=postgresql+asyncpg://... \\
        python scripts/migrate-image-urls.py --apply

    # Apply + prune the SAF-SYNC test artifact (still requires --apply):
    DATABASE_URL=postgresql+asyncpg://... \\
        python scripts/migrate-image-urls.py --apply --prune-test-artifacts
"""

from __future__ import annotations

import argparse
import os
import sys


# The dead host whose absolute URLs we rewrite to relative form.
LEGACY_HOST = "https://partner-demos.jaringan-dagang.metatech.id"

# Image tables to rewrite. Both expose ``url`` as the column; both have
# ``CASCADE`` from their parent (product / sku). The ``cls`` field is only
# used in human-readable output.
IMAGE_TABLES: tuple[str, ...] = ("product_images", "sku_images")

# The SAF-SYNC artifact (live SKU): a single test product with one image
# pointing at example.com. Deleting the product cascades to its skus +
# product_images + sku_images thanks to the FK ``ondelete='CASCADE'``.
SAF_SYNC_SKU_STEM = "SAF-SYNC-1778935890"


def _update_sql_for(table: str) -> str:
    """Return the idempotent UPDATE for one image table.

    Uses Postgres ``REPLACE(url, LEGACY_HOST, '')`` so an absolute URL like
    ``https://partner-demos.jaringan-dagang.metatech.id/brands/foo.svg``
    becomes ``/brands/foo.svg`` — the relative shape the catalog builder
    expects. The WHERE filters on the legacy substring so re-running after
    a successful migration is a no-op (0 rows match).
    """
    return (
        f"UPDATE {table} "
        f"SET url = REPLACE(url, '{LEGACY_HOST}', '') "
        f"WHERE url LIKE '%{LEGACY_HOST.split('://', 1)[1]}%';"
    )


def _prune_saf_sync_sql() -> str:
    """DELETE the SAF-SYNC test artifact, cascading to its images/skus.

    Filtered by SKU stem (``SAF-SYNC-1778935890``). Idempotent: re-running
    after the row is gone matches 0 rows.
    """
    return (
        f"DELETE FROM products WHERE sku = '{SAF_SYNC_SKU_STEM}';"
    )


def print_dry_run_sql(*, prune_test_artifacts: bool = False) -> None:
    """Print the UPDATE / DELETE statements that --apply would execute.

    Safe — no DB connection, no env vars required.
    """
    print("-- jaringan-dagang-seller / migrate-image-urls.py (dry-run)")
    print(
        f"-- Task A7 — rewrite legacy '{LEGACY_HOST}' image URLs to relative "
        "paths in the two image tables."
    )
    print()
    print("BEGIN;")
    for table in IMAGE_TABLES:
        print(_update_sql_for(table))
    if prune_test_artifacts:
        print()
        print(
            f"-- --prune-test-artifacts: drop the SAF-SYNC ('{SAF_SYNC_SKU_STEM}') "
            "demo product and cascade its skus/images."
        )
        print(_prune_saf_sync_sql())
    print("COMMIT;")
    print()
    print("-- Re-running is a no-op once applied:")
    print("--   * Each UPDATE filters by the legacy host substring; once")
    print("--     rewritten, no rows match.")
    if prune_test_artifacts:
        print("--   * DELETE filters by SKU stem; once gone, no rows match.")
    if not prune_test_artifacts:
        print()
        print(
            "-- Pass --prune-test-artifacts to ALSO delete the SAF-SYNC test "
            "product. Default is off (mass-delete safety)."
        )


async def apply_migration(
    database_url: str, *, prune_test_artifacts: bool = False
) -> dict[str, int]:
    """Apply the migration. Returns ``{table_name: rows_updated, ...}``.

    Imports asyncpg / sqlalchemy lazily so dry-run mode never needs them.
    """
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy import text

    engine = create_async_engine(database_url)
    counts: dict[str, int] = {}
    async with engine.begin() as conn:
        for table in IMAGE_TABLES:
            result = await conn.execute(
                text(
                    f"UPDATE {table} "
                    f"SET url = REPLACE(url, :host, '') "
                    f"WHERE url LIKE :pat"
                ),
                {"host": LEGACY_HOST, "pat": f"%{LEGACY_HOST}%"},
            )
            counts[table] = result.rowcount or 0
            print(f"  {table}: {counts[table]} row(s) rewritten")
        if prune_test_artifacts:
            result = await conn.execute(
                text("DELETE FROM products WHERE sku = :stem"),
                {"stem": SAF_SYNC_SKU_STEM},
            )
            counts["products(saf_sync)"] = result.rowcount or 0
            print(f"  products(SAF-SYNC): {counts['products(saf_sync)']} row(s) deleted")
    await engine.dispose()
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Rewrite legacy 'partner-demos.jaringan-dagang.metatech.id' image "
            "URLs in product_images / sku_images to relative paths so the "
            "catalog builder can prepend the per-store image_base_url at "
            "emission time. Default is dry-run (print SQL only)."
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
    parser.add_argument(
        "--prune-test-artifacts",
        action="store_true",
        help=(
            f"Also delete the SAF-SYNC ({SAF_SYNC_SKU_STEM}) test product "
            "row (cascading to its skus/images). Off by default — opt in "
            "explicitly because this DELETEs rows."
        ),
    )
    args = parser.parse_args()

    if not args.apply:
        print_dry_run_sql(prune_test_artifacts=args.prune_test_artifacts)
        return 0

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print(
            "ERROR: --apply requires DATABASE_URL to be set in the environment.",
            file=sys.stderr,
        )
        return 2

    import asyncio

    print(f"Applying image-URL migration against {db_url[:40]}...")
    counts = asyncio.run(
        apply_migration(
            db_url, prune_test_artifacts=args.prune_test_artifacts
        )
    )
    total = sum(counts.values())
    print(f"done. {total} row(s) touched across {len(counts)} statement(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
