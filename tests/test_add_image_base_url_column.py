"""Task A7 — ``scripts/add-image-base-url-column.py`` adds the
``image_base_url`` column to the ``stores`` table (idempotently, via
Postgres ``ADD COLUMN IF NOT EXISTS``) and backfills the Safiya row to
``https://safiya.beliaman.com``.

Default mode is dry-run: prints the SQL and exits. ``--apply`` requires
``DATABASE_URL``.

The no-Alembic seller schema is created by ``Base.metadata.create_all`` —
that's idempotent for tables but does NOT add new columns to existing
tables, so this one-shot ALTER is needed before the migration script can
do its job end-to-end.
"""

from __future__ import annotations

import importlib.util
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

_SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "add-image-base-url-column.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "add_image_base_url_column", _SCRIPT_PATH
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["add_image_base_url_column"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_script_exists():
    assert _SCRIPT_PATH.exists()


def test_script_importable_without_side_effects():
    mod = _load_module()
    assert hasattr(mod, "print_dry_run_sql")


def test_dry_run_emits_idempotent_alter():
    mod = _load_module()
    buf = io.StringIO()
    with redirect_stdout(buf):
        mod.print_dry_run_sql()
    out = buf.getvalue()
    assert "ALTER TABLE stores" in out
    assert "ADD COLUMN IF NOT EXISTS image_base_url" in out, (
        "must use Postgres 'ADD COLUMN IF NOT EXISTS' for idempotency"
    )


def test_dry_run_backfills_safiya_row():
    """The dry-run must include a one-time UPDATE that sets the Safiya store
    to https://safiya.beliaman.com so the storefront base is wired up
    immediately after the ALTER. UPDATE must be idempotent: WHERE clause
    targets the canonical subscriber_id, and the value is fixed."""
    mod = _load_module()
    buf = io.StringIO()
    with redirect_stdout(buf):
        mod.print_dry_run_sql()
    out = buf.getvalue()
    assert "UPDATE stores" in out
    assert "https://safiya.beliaman.com" in out
    assert "safiyafood.jaringan-dagang.id" in out, (
        "backfill UPDATE must target Safiya by canonical subscriber_id"
    )
    assert "WHERE" in out


def test_apply_requires_database_url(monkeypatch):
    mod = _load_module()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(sys, "argv", ["add-image-base-url-column.py", "--apply"])
    rc = mod.main()
    assert rc != 0
