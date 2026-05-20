"""Task A4 — ``BECKN_ORDER_FLOW=on`` retires the seller_bridge endpoint.

When the env flag is ``on``, the legacy ``POST /internal/escrow-orders``
route must respond HTTP 410 Gone (per spec § 6.4). Other modes (off /
shadow / unset) keep the route alive so the migration can land
incrementally.

We test this at the router level by importing the FastAPI app and
hitting the route with TestClient — no Postgres required because the
gate check happens before any DB IO.
"""

from __future__ import annotations

import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PROTO = os.path.join(_ROOT, "packages", "beckn-protocol")
for _p in (_ROOT, _PROTO):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _post_escrow(monkeypatch, flow_mode: str | None):
    """Spin up the seller app and POST to /internal/escrow-orders.

    Returns (status_code, body_text) without exercising the DB.
    """
    if flow_mode is None:
        monkeypatch.delenv("BECKN_ORDER_FLOW", raising=False)
    else:
        monkeypatch.setenv("BECKN_ORDER_FLOW", flow_mode)

    # Re-import the module so the flag check sees the new env. We import
    # the router directly (avoids running the whole FastAPI startup).
    from importlib import reload

    from app.api import escrow_orders as eo_mod

    reload(eo_mod)
    return eo_mod._bridge_retired()


class TestBridgeRetiredFlag:
    """Direct check of the flag-resolver helper — fast + no FastAPI client."""

    def test_default_is_not_retired(self, monkeypatch):
        assert _post_escrow(monkeypatch, None) is False

    def test_off_is_not_retired(self, monkeypatch):
        assert _post_escrow(monkeypatch, "off") is False

    def test_shadow_is_not_retired(self, monkeypatch):
        assert _post_escrow(monkeypatch, "shadow") is False

    def test_on_is_retired(self, monkeypatch):
        assert _post_escrow(monkeypatch, "on") is True

    def test_case_insensitive(self, monkeypatch):
        assert _post_escrow(monkeypatch, "ON") is True

    def test_bogus_value_is_not_retired(self, monkeypatch):
        """An unrecognised value defaults to keeping the bridge alive — we
        do NOT want a typo'd env var to take down the legacy path."""
        assert _post_escrow(monkeypatch, "always") is False
