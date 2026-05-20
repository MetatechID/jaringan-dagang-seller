"""Task A4 — quote_token issuance + verification.

Covers the 10-min HMAC token issued by /on_init and echoed by the BAP on
/confirm. The token is opaque to the buyer; we just need symmetric
issue→verify within this process and the right failure modes.
"""

from __future__ import annotations

import os
import sys
import time

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PROTO = os.path.join(_ROOT, "packages", "beckn-protocol")
for _p in (_ROOT, _PROTO):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.beckn.quote_token import (  # noqa: E402
    QUOTE_TTL_SECS,
    build_quote_token,
    verify_quote_token,
)


CART = [{"sku_id": "sku-A", "qty": 2}, {"sku_id": "sku-B", "qty": 1}]


class TestRoundtrip:
    def test_freshly_issued_token_verifies(self):
        token = build_quote_token(items=CART, total=50000)
        ok, err = verify_quote_token(token)
        assert ok, err
        assert err is None

    def test_items_and_total_match_passes(self):
        token = build_quote_token(items=CART, total=50000)
        ok, err = verify_quote_token(token, items=CART, total=50000)
        assert ok, err

    def test_item_order_does_not_affect_match(self):
        token = build_quote_token(items=CART, total=50000)
        reordered = list(reversed(CART))
        ok, err = verify_quote_token(token, items=reordered, total=50000)
        assert ok, err

    def test_beckn_shape_items_normalize_to_match(self):
        """Items in Beckn ``{id, quantity.selected.count}`` shape match
        equivalent ``{sku_id, qty}`` shape."""
        token = build_quote_token(items=CART, total=50000)
        beckn_shape = [
            {"id": "sku-A", "quantity": {"selected": {"count": 2}}},
            {"id": "sku-B", "quantity": {"selected": {"count": 1}}},
        ]
        ok, err = verify_quote_token(token, items=beckn_shape, total=50000)
        assert ok, err


class TestFailureModes:
    def test_malformed_token(self):
        ok, err = verify_quote_token("not.a.real.token")
        assert not ok and err == "malformed"

    def test_empty_token(self):
        ok, err = verify_quote_token("")
        assert not ok and err == "malformed"

    def test_bad_signature(self):
        token = build_quote_token(items=CART, total=50000)
        body, _ = token.split(".")
        tampered = f"{body}.AAAAAAAA"
        ok, err = verify_quote_token(tampered)
        assert not ok and err == "bad_signature"

    def test_expired_token(self):
        # Issued >TTL ago
        token = build_quote_token(
            items=CART, total=50000,
            issued_at=time.time() - (QUOTE_TTL_SECS + 60),
        )
        ok, err = verify_quote_token(token)
        assert not ok and err == "expired"

    def test_items_mismatch(self):
        token = build_quote_token(items=CART, total=50000)
        ok, err = verify_quote_token(
            token,
            items=[{"sku_id": "sku-A", "qty": 99}],
            total=50000,
        )
        assert not ok and err == "items_mismatch"

    def test_total_mismatch(self):
        token = build_quote_token(items=CART, total=50000)
        ok, err = verify_quote_token(token, items=CART, total=999999)
        assert not ok and err == "total_mismatch"
