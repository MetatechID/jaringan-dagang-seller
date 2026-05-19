"""Task A1 — seller BPP outbound context carries the resolved ONDC domain.

The two seller emission sites must stamp the per-store ONDC domain code
resolved from the store's ``subscriber_id`` rather than the raw
``settings.BECKN_DOMAIN`` Beckn base:

  * ``app/beckn/status_push.py``  -> ``_ctx``         (/on_status)
  * ``app/beckn/catalog_push.py`` -> ``_build_context`` (/on_search)

For Safiya (``safiyafood.jaringan-dagang.id``) the envelope must carry
``domain == "ONDC:RET11"``; an unknown / missing store falls back to the
resolver's documented store-level ``ONDC:RET`` default. The Beckn
transport base stays ``nic2004:52110`` regardless.
"""

import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PROTO = os.path.join(_ROOT, "packages", "beckn-protocol")
for _p in (_ROOT, _PROTO):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.beckn.catalog_push import _build_context  # noqa: E402
from app.beckn.status_push import _ctx  # noqa: E402

SAFIYA = "safiyafood.jaringan-dagang.id"


class TestStatusPushContext:
    def test_safiya_on_status_carries_ondc_ret11(self):
        ctx = _ctx(
            bap_id="beli-aman.bap.jaringan-dagang.id",
            bap_uri="http://bap",
            bpp_id="bpp.jaringan-dagang.local",
            bpp_uri="http://bpp",
            txn_id="t1",
            store_subscriber_id=SAFIYA,
        )
        assert ctx["domain"] == "ONDC:RET11"

    def test_unknown_store_falls_back_to_retail_default(self):
        ctx = _ctx(
            bap_id="b",
            bap_uri="u",
            bpp_id="p",
            bpp_uri="pu",
            txn_id="t2",
            store_subscriber_id="nope.example.id",
        )
        assert ctx["domain"] == "ONDC:RET"

    def test_missing_store_falls_back_to_retail_default(self):
        ctx = _ctx(
            bap_id="b",
            bap_uri="u",
            bpp_id="p",
            bpp_uri="pu",
            txn_id="t3",
        )
        assert ctx["domain"] == "ONDC:RET"


class TestCatalogPushContext:
    def test_safiya_on_search_carries_ondc_ret11(self):
        ctx = _build_context(
            "beli-aman.bap.jaringan-dagang.id",
            "http://bap",
            store_subscriber_id=SAFIYA,
        )
        assert ctx["domain"] == "ONDC:RET11"

    def test_multi_or_unknown_store_uses_retail_default(self):
        ctx = _build_context("beli-aman.bap.jaringan-dagang.id", "http://bap")
        assert ctx["domain"] == "ONDC:RET"
