"""Tests for the per-store ONDC domain resolver — seller mirror.

The resolver lives in the shared beckn-protocol package
(``packages/beckn-protocol/python/domain_resolver.py``) so both the
seller (BPP) and buyer (BAP) consume an identical implementation. The
buyer copy is the canonical upstream (per the A2.5 docstring fix); this
seller mirror is byte-identical to it.

Source of truth for the mapping: the network ONDC localization layer at
``jaringan-dagang-network/network-extension/domains/retail.yaml``
(``domain.code: ONDC:RET``; sub-domains: ``ONDC:RET11`` "F&B (Packaged)",
``ONDC:RET12`` "Fashion", ``ONDC:RET15`` "Health & Beauty" — all on the
same Beckn retail transport base ``nic2004:52110``).

Task A3 extends A1's mapping with the *canonical* subscriber_id scheme
``*.jaringan-dagang.id`` for every onboarded store. Legacy ``bpp.*.local``
identifiers MUST fall back cleanly to the documented store-level default
(no special-case in the table — they are simply not canonical and the
expectation is that the live DB rows get migrated to the canonical form).
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
    ONDC_RETAIL_BECKN_BASE,
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


class TestMatchamuResolvesToPackagedFnB:
    """Matchamu is a packaged matcha & powder beverages store -> ONDC:RET11."""

    def test_by_subscriber_id(self):
        result = resolve_ondc_domain("matchamu.jaringan-dagang.id")
        assert result.domain_code == "ONDC:RET11"
        assert result.beckn_domain == "nic2004:52110"

    def test_by_slug(self):
        result = resolve_ondc_domain("matchamu")
        assert result.domain_code == "ONDC:RET11"
        assert result.beckn_domain == "nic2004:52110"


class TestOptimumNutritionResolvesToHealthAndBeauty:
    """Optimum Nutrition is a sports supplements store -> ONDC:RET15."""

    def test_by_subscriber_id(self):
        result = resolve_ondc_domain("optimumnutrition.jaringan-dagang.id")
        assert result.domain_code == "ONDC:RET15"
        assert result.beckn_domain == "nic2004:52110"

    def test_by_slug(self):
        result = resolve_ondc_domain("optimumnutrition")
        assert result.domain_code == "ONDC:RET15"
        assert result.beckn_domain == "nic2004:52110"


class TestAntarestarResolvesToFashion:
    """Antarestar sells jackets / daypacks -> ONDC:RET12 (Fashion)."""

    def test_by_subscriber_id(self):
        result = resolve_ondc_domain("antarestar.jaringan-dagang.id")
        assert result.domain_code == "ONDC:RET12"
        assert result.beckn_domain == "nic2004:52110"

    def test_by_slug(self):
        result = resolve_ondc_domain("antarestar")
        assert result.domain_code == "ONDC:RET12"
        assert result.beckn_domain == "nic2004:52110"


class TestGendesResolvesToHealthAndBeauty:
    """Gendes sells feminine-care wash / spray -> ONDC:RET15 (Health & Beauty)."""

    def test_by_subscriber_id(self):
        result = resolve_ondc_domain("gendes.jaringan-dagang.id")
        assert result.domain_code == "ONDC:RET15"
        assert result.beckn_domain == "nic2004:52110"

    def test_by_slug(self):
        result = resolve_ondc_domain("gendes")
        assert result.domain_code == "ONDC:RET15"
        assert result.beckn_domain == "nic2004:52110"


class TestYourBrandIsDemoFallback:
    """YourBrand is the white-label demo toko (no real catalogue mix).

    It deliberately stays on the store-level retail default; we don't
    pretend to know its sub-domain.
    """

    def test_yourbrand_by_canonical_id_uses_default(self):
        result = resolve_ondc_domain("yourbrand.jaringan-dagang.id")
        assert result == DEFAULT_ONDC_DOMAIN
        assert result.domain_code == "ONDC:RET"

    def test_yourbrand_slug_uses_default(self):
        result = resolve_ondc_domain("yourbrand")
        assert result == DEFAULT_ONDC_DOMAIN
        assert result.domain_code == "ONDC:RET"


class TestLegacyIdentifiersFallBackCleanly:
    """Legacy ``bpp.*.local`` / ``*.bpp.metatech.id`` identifiers MUST
    resolve to the store-level retail default — they are not in the table.

    The expectation is the live DB is migrated to the canonical scheme;
    until then, an order with a legacy bpp_id stays on the retail base
    and just loses the sub-domain specificity.
    """

    def test_legacy_metatech_subscriber_id(self):
        assert resolve_ondc_domain("safiyafood.bpp.metatech.id") == DEFAULT_ONDC_DOMAIN

    def test_legacy_bpp_local_subscriber_id(self):
        assert resolve_ondc_domain("bpp.antarestar.local") == DEFAULT_ONDC_DOMAIN

    def test_legacy_single_tenant_fallback(self):
        # bpp.jaringan-dagang.local was the seller-fallback before A3;
        # canonical is bpp.jaringan-dagang.id.
        assert resolve_ondc_domain("bpp.jaringan-dagang.local") == DEFAULT_ONDC_DOMAIN


class TestCanonicalFallbackIdentifier:
    """The canonical single-tenant fallback ``bpp.jaringan-dagang.id``
    is NOT a per-store id and therefore intentionally uses the default —
    catalogue mix is unknown.
    """

    def test_canonical_fallback_uses_default(self):
        result = resolve_ondc_domain("bpp.jaringan-dagang.id")
        assert result == DEFAULT_ONDC_DOMAIN
        assert result.domain_code == "ONDC:RET"


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
        """Every mapped store keeps the nic2004:52110 transport base.

        A3 adds canonical-id entries; the Beckn base is invariant.
        """
        for ident in (
            "safiyafood",
            "safiyafood.jaringan-dagang.id",
            "matchamu.jaringan-dagang.id",
            "optimumnutrition.jaringan-dagang.id",
            "antarestar.jaringan-dagang.id",
            "gendes.jaringan-dagang.id",
            "yourbrand.jaringan-dagang.id",
            "bpp.jaringan-dagang.id",
            "bpp.antarestar.local",  # legacy
            None,
            "x",
        ):
            assert resolve_ondc_domain(ident).beckn_domain == ONDC_RETAIL_BECKN_BASE
