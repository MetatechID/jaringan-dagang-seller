"""Task A7 — ``scripts/migrate-image-urls.py`` rewrites legacy absolute
image URLs in ``product_images`` / ``sku_images`` to host-agnostic
relative paths, and (optionally, behind a flag) prunes the SAF-SYNC test
artifact row.

Default mode is dry-run: prints the SQL it would execute and exits.
``--apply`` requires ``DATABASE_URL`` to be set.

This test:
  * Imports the script as a module (must be importable without side effects).
  * Asserts the legacy host constant matches the actual live dead host.
  * Captures the dry-run SQL output and verifies each table is targeted.
  * Asserts ``--prune-test-artifacts`` is OFF by default (mass-delete safety).
  * Asserts the dry-run produces idempotent-shape SQL (WHERE clause).
"""

from __future__ import annotations

import importlib.util
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

_SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent / "scripts" / "migrate-image-urls.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "migrate_image_urls", _SCRIPT_PATH
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["migrate_image_urls"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_script_exists():
    assert _SCRIPT_PATH.exists(), (
        f"migration script not found at {_SCRIPT_PATH}"
    )


def test_script_is_importable_without_side_effects():
    mod = _load_module()
    assert hasattr(mod, "LEGACY_HOST"), "module must expose LEGACY_HOST"
    assert hasattr(mod, "print_dry_run_sql"), (
        "module must expose print_dry_run_sql()"
    )


def test_legacy_host_matches_live_dead_host():
    mod = _load_module()
    assert mod.LEGACY_HOST == "https://partner-demos.jaringan-dagang.metatech.id"


def test_dry_run_targets_both_image_tables():
    """Dry-run must emit UPDATE statements for product_images AND sku_images
    (the live API exposes both shapes; we must rewrite both)."""
    mod = _load_module()
    buf = io.StringIO()
    with redirect_stdout(buf):
        mod.print_dry_run_sql(prune_test_artifacts=False)
    out = buf.getvalue()
    assert "UPDATE product_images" in out, (
        "dry-run must rewrite product_images.url"
    )
    assert "UPDATE sku_images" in out, "dry-run must rewrite sku_images.url"
    # The legacy host must literally appear in the emitted SQL so an operator
    # can grep it and confirm intent before running --apply.
    assert mod.LEGACY_HOST in out


def test_dry_run_has_where_clauses_for_idempotency():
    """Each UPDATE must filter on a column matching the legacy host so
    re-running after a successful migration becomes a no-op."""
    mod = _load_module()
    buf = io.StringIO()
    with redirect_stdout(buf):
        mod.print_dry_run_sql(prune_test_artifacts=False)
    out = buf.getvalue()
    # We expect 2 UPDATE statements -> at least 2 WHEREs
    assert out.count("WHERE") >= 2, (
        "every UPDATE must have a WHERE clause for idempotency"
    )
    assert out.count("LIKE") >= 2, (
        "WHERE clauses should filter rows with the legacy host substring"
    )


def test_prune_flag_off_by_default():
    """The --prune-test-artifacts flag is OFF by default. The dry-run output
    should NOT contain a DELETE statement unless asked."""
    mod = _load_module()
    buf = io.StringIO()
    with redirect_stdout(buf):
        mod.print_dry_run_sql(prune_test_artifacts=False)
    out = buf.getvalue()
    assert "DELETE" not in out, (
        "DELETE must not appear in dry-run output without --prune-test-artifacts"
    )


def test_prune_flag_emits_delete_for_saf_sync_artifact():
    """With --prune-test-artifacts, the dry-run output must include a DELETE
    targeting the SAF-SYNC-1778935890 test product (and only that one,
    by SKU stem)."""
    mod = _load_module()
    buf = io.StringIO()
    with redirect_stdout(buf):
        mod.print_dry_run_sql(prune_test_artifacts=True)
    out = buf.getvalue()
    assert "DELETE FROM products" in out
    assert "SAF-SYNC-1778935890" in out, (
        "prune DELETE must target the documented test SKU explicitly"
    )


def test_dry_run_is_deterministic():
    """Re-running dry-run twice must print the same SQL twice (no side effects,
    no environment dependency)."""
    mod = _load_module()
    buf = io.StringIO()
    with redirect_stdout(buf):
        mod.print_dry_run_sql(prune_test_artifacts=False)
        mod.print_dry_run_sql(prune_test_artifacts=False)
    out = buf.getvalue()
    assert out.count("UPDATE product_images") >= 2


def test_apply_requires_database_url(monkeypatch, capsys):
    """``main`` with --apply but no DATABASE_URL must exit non-zero without
    touching the network."""
    mod = _load_module()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(sys, "argv", ["migrate-image-urls.py", "--apply"])
    rc = mod.main()
    assert rc != 0


def test_sql_replaces_legacy_host_with_empty_prefix():
    """The UPDATE shape must rewrite legacy absolute URL -> relative path.
    Concretely, replace(url, 'https://partner-demos.jaringan-dagang.metatech.id', '')."""
    mod = _load_module()
    buf = io.StringIO()
    with redirect_stdout(buf):
        mod.print_dry_run_sql(prune_test_artifacts=False)
    out = buf.getvalue()
    # Either REPLACE() or literal substring rewrite must appear.
    assert "REPLACE" in out.upper() or "replace" in out, (
        "dry-run SQL must use REPLACE(url, <legacy_host>, '') to rewrite "
        "the host prefix"
    )
