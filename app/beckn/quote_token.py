"""10-minute signed quote token for Beckn /on_init → /confirm (Task A4).

Per spec § 6.1, the seller's /on_init returns a ``quote_token`` covering
``(items, total, expires_at)``; the BAP echoes it on /confirm so the seller
can refuse stale quotes (e.g. user takes >10 min to pay and price drifted).

Implementation notes
--------------------

* HMAC-SHA256 over a canonical-JSON payload, with an 8-char prefix as the
  key id. The secret comes from env ``QUOTE_TOKEN_SECRET`` (auto-generated
  per-process if unset, which is sufficient for dev since the same process
  issues and verifies — production should set it explicitly).
* The token is **opaque to the buyer**: it's base64url(payload).base64url(sig).
  The buyer doesn't need to read it; it only echoes it. The verifier
  re-derives the payload from the echoed string, checks signature + expiry.
* Items are normalized into a stable shape (sorted by sku_id, qty coerced
  to int) before hashing so equivalent carts produce equivalent tokens.

This is intentionally NOT a full JWT — we don't need claims-parsing tooling,
just "did we issue this, and is it still fresh."
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from typing import Any, Iterable

logger = logging.getLogger(__name__)

# Quote validity (spec § 6.1: "10-min price quote").
QUOTE_TTL_SECS = 600

# Per-process secret fallback. Production should set QUOTE_TOKEN_SECRET so a
# rolling deploy doesn't invalidate in-flight quotes; for dev/test a fresh
# random secret per import is fine (verifies within the same process).
_FALLBACK_SECRET = secrets.token_hex(32)


def _secret() -> bytes:
    env = os.environ.get("QUOTE_TOKEN_SECRET") or ""
    return (env or _FALLBACK_SECRET).encode()


def _b64u_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64u_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode((s + pad).encode())


def _canonical_items(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize items list to a stable form.

    Accepts either Beckn ``{id, quantity.selected.count}`` or the seller's
    internal ``{sku_id, qty}`` shape. Output is sorted by ``sku_id``.
    """
    out: list[dict[str, Any]] = []
    for it in items or []:
        sku_id = it.get("sku_id") or it.get("id") or ""
        qty = it.get("qty")
        if qty is None:
            qty = (
                ((it.get("quantity") or {}).get("selected") or {}).get("count")
                or (it.get("quantity") or {}).get("count")
                or 1
            )
        out.append({"sku_id": str(sku_id), "qty": int(qty)})
    out.sort(key=lambda x: x["sku_id"])
    return out


def build_quote_token(
    *,
    items: Iterable[dict[str, Any]],
    total: int | float | str,
    issued_at: float | None = None,
) -> str:
    """Issue a 10-min HMAC-signed quote token covering items+total.

    Returns the opaque ``<payload>.<sig>`` string.
    """
    now = int(issued_at if issued_at is not None else time.time())
    payload = {
        "items": _canonical_items(items),
        "total": int(float(str(total or 0))),
        "iat": now,
        "exp": now + QUOTE_TTL_SECS,
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    sig = hmac.new(_secret(), body, hashlib.sha256).digest()
    return f"{_b64u_encode(body)}.{_b64u_encode(sig)}"


def verify_quote_token(
    token: str,
    *,
    items: Iterable[dict[str, Any]] | None = None,
    total: int | float | str | None = None,
    now: float | None = None,
) -> tuple[bool, str | None]:
    """Verify a quote token. Returns (ok, error_code).

    Error codes (when ok=False):
      - ``malformed``: not a ``<a>.<b>`` string we issued
      - ``bad_signature``: HMAC mismatch (wrong secret or tampered)
      - ``expired``: now > payload.exp
      - ``items_mismatch``: items arg given and doesn't match issued payload
      - ``total_mismatch``: total arg given and doesn't match issued payload
    """
    if not token or "." not in token:
        return False, "malformed"
    try:
        body_b64, sig_b64 = token.split(".", 1)
        body = _b64u_decode(body_b64)
        sig = _b64u_decode(sig_b64)
    except Exception:
        return False, "malformed"

    expected_sig = hmac.new(_secret(), body, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected_sig):
        return False, "bad_signature"

    try:
        payload = json.loads(body.decode())
    except Exception:
        return False, "malformed"

    ts_now = int(now if now is not None else time.time())
    if payload.get("exp", 0) <= ts_now:
        return False, "expired"

    if items is not None:
        if _canonical_items(items) != payload.get("items"):
            return False, "items_mismatch"
    if total is not None:
        if int(float(str(total or 0))) != int(payload.get("total") or 0):
            return False, "total_mismatch"

    return True, None
