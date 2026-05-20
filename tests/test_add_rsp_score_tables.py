"""Task A6 — ``scripts/add-rsp-score-tables.py`` + ``add-refund-bap-issue-id-column.py``.

Both follow the dry-run-default pattern from A5's
``add-dispute-issue-columns.py``: default prints SQL, ``--apply``
requires ``DATABASE_URL``.
"""

from __future__ import annotations

import importlib.util
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

_RSP_SCORE = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "add-rsp-score-tables.py"
)
_REFUND_COL = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "add-refund-bap-issue-id-column.py"
)


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_rsp_score_script_exists():
    assert _RSP_SCORE.exists()


def test_refund_col_script_exists():
    assert _REFUND_COL.exists()


def test_rsp_score_dry_run_creates_both_tables():
    mod = _load(_RSP_SCORE, "add_rsp_score_tables")
    buf = io.StringIO()
    with redirect_stdout(buf):
        mod.print_dry_run_sql()
    out = buf.getvalue()
    assert "settlement_ledger" in out
    assert "score_snapshots" in out
    # Enum types must be DDL'd before tables.
    assert "settlement_basis" in out
    assert "settlement_window" in out
    assert "settlement_status" in out
    # Idempotency guards.
    assert "IF NOT EXISTS" in out
    assert "duplicate_object" in out
    # Indexes for the lookup paths.
    assert "ix_settlement_ledger_status" in out
    assert "ix_score_snapshots_store_band" in out
    assert "uq_score_snapshots_store_period" in out


def test_rsp_score_apply_requires_database_url(monkeypatch):
    mod = _load(_RSP_SCORE, "add_rsp_score_tables")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(sys, "argv", ["add-rsp-score-tables.py", "--apply"])
    rc = mod.main()
    assert rc != 0


def test_refund_col_dry_run_adds_column_and_index():
    mod = _load(_REFUND_COL, "add_refund_bap_issue_id_column")
    buf = io.StringIO()
    with redirect_stdout(buf):
        mod.print_dry_run_sql()
    out = buf.getvalue()
    assert "bap_issue_id" in out
    assert "ADD COLUMN IF NOT EXISTS" in out
    assert "CREATE INDEX IF NOT EXISTS" in out
    assert "ix_refund_requests_bap_issue_id" in out
    # Back-fill must be there + must skip already-converged rows.
    assert "SUBSTRING" in out or "REGEXP" in out
    assert "bap_issue_id IS NULL" in out


def test_refund_col_apply_requires_database_url(monkeypatch):
    mod = _load(_REFUND_COL, "add_refund_bap_issue_id_column")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(
        sys, "argv", ["add-refund-bap-issue-id-column.py", "--apply"]
    )
    rc = mod.main()
    assert rc != 0
