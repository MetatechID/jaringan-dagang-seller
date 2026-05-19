"""Tests for the per-store ONDC domain resolver (Task A1).

The resolver lives in the shared beckn-protocol package
(``packages/beckn-protocol/python/domain_resolver.py``) so both the
seller (BPP) and buyer (BAP) consume an identical implementation.

Source of truth for the mapping: the network ONDC localization layer at
``jaringan-dagang-network/network-extension/domains/retail.yaml``
(``domain.code: ONDC:RET``; sub-domain ``ONDC:RET11`` "F&B (Packaged)"
-> ``beckn_domain: nic2004:52110``).
"""

import os
import sys

import pytest

_PROTO = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "packages", "beckn-protocol")
)
if _PROTO not in sys.path:
    sys.path.insert(0, _PROTO)

from python.domain_resolver import (  # noqa: E402
    DEFAULT_ONDC_DOMAIN,
    OndcDomain,
    resolve_ondc_domain,
)


class TestSafiyaResolvesToPackagedFnB:
    """Safiya is a packaged-F&B store -> ONDC:RET11 / nic2004:52110."""

    def test_by_live_subscriber_id(self):
        result = resolve_ondc_domain("safiyafood.jaringan-dagang.id")
        assert result.domain_code == "ONDC:RET11"
        assert result.beckn_domain == "nic2004:52110"

    def test_by_slug(self):
        result = resolve_ondc_domain("safiyafood")
        assert result.domain_code == "ONDC:RET11"
        assert result.beckn_domain == "nic2004:52110"

    def test_is_case_insensitive_and_trims(self):
        result = resolve_ondc_domain("  SafiyaFood  ")
        assert result.domain_code == "ONDC:RET11"
        assert result.beckn_domain == "nic2004:52110"


class TestUnknownStoreUsesDocumentedDefault:
    """Unknown / missing store -> store-level retail default.

    The base Beckn domain stays nic2004:52110 (retail transport base);
    the ONDC code falls back to the store-level ``ONDC:RET`` rather than a
    specific sub-domain, since we cannot infer the catalogue mix.
    """

    def test_unknown_subscriber(self):
        result = resolve_ondc_domain("someone-else.example.id")
        assert result == DEFAULT_ONDC_DOMAIN
        assert result.domain_code == "ONDC:RET"
        assert result.beckn_domain == "nic2004:52110"

    def test_none(self):
        assert resolve_ondc_domain(None) == DEFAULT_ONDC_DOMAIN

    def test_empty_string(self):
        assert resolve_ondc_domain("") == DEFAULT_ONDC_DOMAIN

    def test_whitespace_only(self):
        assert resolve_ondc_domain("   ") == DEFAULT_ONDC_DOMAIN


class TestOndcDomainValueObject:
    """The returned value object is a frozen, comparable pair."""

    def test_frozen(self):
        d = resolve_ondc_domain("safiyafood")
        with pytest.raises(Exception):
            d.domain_code = "ONDC:RET10"  # type: ignore[misc]

    def test_equality_by_value(self):
        assert resolve_ondc_domain("safiyafood") == OndcDomain(
            domain_code="ONDC:RET11", beckn_domain="nic2004:52110"
        )

    def test_beckn_transport_base_unchanged(self):
        """Every retail mapping keeps the nic2004:52110 transport base.

        A1 adds an ONDC code layer; it must NOT change the Beckn base.
        """
        for ident in ("safiyafood", "safiyafood.jaringan-dagang.id", None, "x"):
            assert resolve_ondc_domain(ident).beckn_domain == "nic2004:52110"
