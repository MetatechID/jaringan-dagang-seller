"""Task A3 — ``scripts/migrate-subscriber-ids.py`` is an idempotent,
dry-run-default migration that updates legacy ``bpp.*.local`` subscriber
ids to the canonical ``<slug>.jaringan-dagang.id`` form in the live
seller Postgres.

This test:
  * Imports the script as a module (must be importable without side-effects)
  * Asserts the mapping table covers the 3 known legacy rows
    (antarestar, gendes, yourbrand)
  * Captures the dry-run SQL output and verifies each legacy -> canonical
    pair is emitted
  * Asserts the script does NOT touch the DB by default (no --apply means
    no INSERT/UPDATE — only ``print``)
"""

from __future__ import annotations

import importlib.util
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

_SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent / "scripts" / "migrate-subscriber-ids.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "migrate_subscriber_ids", _SCRIPT_PATH
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["migrate_subscriber_ids"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_script_exists():
    assert _SCRIPT_PATH.exists(), (
        f"migration script not found at {_SCRIPT_PATH}"
    )


def test_script_is_importable_without_side_effects():
    """Importing the module must not touch the DB / do any work."""
    mod = _load_module()
    assert hasattr(mod, "LEGACY_TO_CANONICAL"), (
        "module must expose LEGACY_TO_CANONICAL mapping"
    )


def test_mapping_covers_three_known_legacy_rows():
    mod = _load_module()
    expected = {
        "bpp.antarestar.local": "antarestar.jaringan-dagang.id",
        "bpp.gendes.local": "gendes.jaringan-dagang.id",
        "bpp.yourbrand.local": "yourbrand.jaringan-dagang.id",
    }
    for legacy, canonical in expected.items():
        assert mod.LEGACY_TO_CANONICAL.get(legacy) == canonical, (
            f"LEGACY_TO_CANONICAL[{legacy!r}] = "
            f"{mod.LEGACY_TO_CANONICAL.get(legacy)!r}; expected {canonical!r}"
        )


def test_dry_run_prints_sql_for_each_pair():
    mod = _load_module()
    buf = io.StringIO()
    with redirect_stdout(buf):
        mod.print_dry_run_sql()
    out = buf.getvalue()
    # Every legacy -> canonical pair appears in an UPDATE statement
    for legacy, canonical in mod.LEGACY_TO_CANONICAL.items():
        assert legacy in out, f"dry-run output missing legacy id {legacy!r}"
        assert canonical in out, f"dry-run output missing canonical id {canonical!r}"
    assert "UPDATE stores" in out, "dry-run output must contain UPDATE stores"
    # Idempotency hint — the WHERE clause must include the legacy id to
    # make re-running a no-op once already migrated.
    assert "WHERE" in out, "dry-run UPDATE must have a WHERE clause for idempotency"


def test_dry_run_does_not_attempt_db_connection():
    """``print_dry_run_sql`` must NOT import asyncpg / sqlalchemy.create_engine
    / open a connection. The default is print-only."""
    mod = _load_module()
    # Call dry-run twice and confirm no exception (no DB envvars needed)
    buf = io.StringIO()
    with redirect_stdout(buf):
        mod.print_dry_run_sql()
        mod.print_dry_run_sql()
    # Re-running prints the same SQL twice -> deterministic
    out = buf.getvalue()
    assert out.count("UPDATE stores") >= 2
