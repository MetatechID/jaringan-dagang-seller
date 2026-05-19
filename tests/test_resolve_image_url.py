"""Task A7 — ``BecknCatalogBuilder._resolve_image_url`` joins a per-store
``image_base_url`` with a stored (possibly relative) image path so the
emitted Beckn ``Item.images[].url`` is always a full, fetchable URL.

Why this exists
---------------
Live seller catalog stores image URLs in two shapes:

  * **Legacy absolute** — ``https://partner-demos.jaringan-dagang.metatech.id/
    brands/safiyafood/products/<file>.svg`` (host is DEAD, ECONNREFUSED).
  * **New relative** — ``/brands/safiyafood/products/<file>.svg`` joined
    with ``Store.image_base_url`` (e.g. ``https://safiya.beliaman.com``)
    at the moment Beckn ``Item.images[].url`` is constructed.

The resolver must:

  * pass absolute URLs through unchanged (backward compat during rollout)
  * prepend the per-store base to relative paths
  * be tolerant of trailing-slash on the base (idempotent join)
  * skip cleanly on None / empty stored value
"""

from __future__ import annotations

import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PROTO = os.path.join(_ROOT, "packages", "beckn-protocol")
for _p in (_ROOT, _PROTO):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.beckn.catalog_builder import BecknCatalogBuilder  # noqa: E402


_BASE = "https://safiya.beliaman.com"
_BASE_TRAILING = "https://safiya.beliaman.com/"
_REL = "/brands/safiyafood/products/madu-akasia-front.svg"
_ABS_LEGACY = (
    "https://partner-demos.jaringan-dagang.metatech.id"
    "/brands/safiyafood/products/madu-akasia-front.svg"
)
_ABS_CANONICAL = (
    "https://safiya.beliaman.com/brands/safiyafood/products/"
    "madu-akasia-front.svg"
)


class TestRelativePathJoin:
    def test_relative_joins_with_base(self):
        out = BecknCatalogBuilder._resolve_image_url(_REL, _BASE)
        assert out == _ABS_CANONICAL

    def test_trailing_slash_on_base_is_idempotent(self):
        out = BecknCatalogBuilder._resolve_image_url(_REL, _BASE_TRAILING)
        assert out == _ABS_CANONICAL, (
            "Trailing slash on base must not produce double-slash in the "
            "joined URL."
        )

    def test_relative_without_leading_slash_still_joins(self):
        # Defensive: tolerate a relative value missing the leading slash.
        out = BecknCatalogBuilder._resolve_image_url(
            "brands/safiyafood/products/foo.svg", _BASE
        )
        assert out == "https://safiya.beliaman.com/brands/safiyafood/products/foo.svg"


class TestAbsolutePassThrough:
    def test_https_passes_through_unchanged(self):
        # Legacy absolute URLs (incl. the dead-host ones) MUST pass through
        # unchanged so a half-migrated DB still emits the same shape it has
        # today. The data migration handles rewrite separately.
        out = BecknCatalogBuilder._resolve_image_url(_ABS_LEGACY, _BASE)
        assert out == _ABS_LEGACY

    def test_http_passes_through_unchanged(self):
        url = "http://example.com/foo.png"
        assert BecknCatalogBuilder._resolve_image_url(url, _BASE) == url

    def test_absolute_with_no_base_passes_through(self):
        # Store without a configured image_base_url shouldn't break legacy
        # absolute URLs.
        assert (
            BecknCatalogBuilder._resolve_image_url(_ABS_LEGACY, None)
            == _ABS_LEGACY
        )


class TestEmptyAndMissing:
    def test_none_stored_returns_empty(self):
        assert BecknCatalogBuilder._resolve_image_url(None, _BASE) == ""

    def test_empty_stored_returns_empty(self):
        assert BecknCatalogBuilder._resolve_image_url("", _BASE) == ""

    def test_relative_with_no_base_returns_path_as_is(self):
        # If a store has no image_base_url configured but its rows are
        # relative, we keep the relative form. The emission layer that
        # consumes this can then decide to skip / log — better than
        # fabricating an origin.
        assert BecknCatalogBuilder._resolve_image_url(_REL, None) == _REL

    def test_relative_with_empty_base_returns_path_as_is(self):
        assert BecknCatalogBuilder._resolve_image_url(_REL, "") == _REL


class TestCatalogBuilderUsesResolver:
    """End-to-end: ``_build_images`` / ``_build_sku_images`` must run each
    stored image URL through the resolver, using ``store.image_base_url``
    when a Store is in scope (via ``_sku_to_item`` -> ``build_provider``).

    Verifies that legacy absolute URLs still appear as-is in the emitted
    Beckn Item, AND that relative URLs get prepended with the store base.
    """

    def _make_store(self, image_base_url=None):
        import types
        import uuid

        return types.SimpleNamespace(
            id=uuid.uuid4(),
            name="Safiya Food",
            description="Toko",
            logo_url=None,
            subscriber_id="safiyafood.jaringan-dagang.id",
            image_base_url=image_base_url,
        )

    def _make_product_with_image(self, image_url):
        import types
        import uuid
        from decimal import Decimal

        img = types.SimpleNamespace(url=image_url, position=0)
        sku = types.SimpleNamespace(
            id=uuid.uuid4(),
            sku_code="SKU-1",
            price=Decimal("25000"),
            original_price=None,
            stock=10,
            variant_name=None,
            variant_value=None,
            images=[],
        )
        return sku, types.SimpleNamespace(
            id=uuid.uuid4(),
            name="Madu",
            description="Madu murni",
            images=[img],
            attributes=None,
            category=None,
            skus=[sku],
        )

    def test_provider_emits_relative_path_joined_with_base(self):
        store = self._make_store(image_base_url=_BASE)
        sku, product = self._make_product_with_image(_REL)
        prov = BecknCatalogBuilder.build_provider(store, [product])
        item = prov.items[0]
        # descriptor.images[0].url is the wire-shape URL the BAP sees.
        assert item.descriptor.images is not None
        assert item.descriptor.images[0].url == _ABS_CANONICAL

    def test_provider_passes_through_legacy_absolute_url(self):
        store = self._make_store(image_base_url=_BASE)
        sku, product = self._make_product_with_image(_ABS_LEGACY)
        prov = BecknCatalogBuilder.build_provider(store, [product])
        item = prov.items[0]
        assert item.descriptor.images[0].url == _ABS_LEGACY
