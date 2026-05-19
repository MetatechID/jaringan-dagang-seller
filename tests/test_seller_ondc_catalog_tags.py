"""Task A2 — seller catalog_builder emits ONDC item/fulfillment/payment tags.

Asserts the constructed Beckn objects (Item / Provider fulfillments /
Provider payments) now carry the ONDC ``@ondc/org/...`` tag groups built
by ``python.ondc_tags``. Uses lightweight stand-ins for the ORM rows so
the test stays a fast, DB-free unit test (mirrors the existing
``test_seller_context_domain`` approach).

Scope = on_search / on_select / on_confirm tag emission only (YAGNI). The
control flow of the handlers is unchanged; only the constructed catalog
objects gain tags.
"""

import os
import sys
import types
import uuid
from decimal import Decimal

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PROTO = os.path.join(_ROOT, "packages", "beckn-protocol")
for _p in (_ROOT, _PROTO):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app.beckn.catalog_builder import BecknCatalogBuilder  # noqa: E402
from python.ondc_tags import (  # noqa: E402
    ONDC_ORG_STATUTORY_PACKAGED_COMMODITIES,
    ONDC_ORG_STATUTORY_PREPACKAGED_FOOD,
)


def _img(url, position=0):
    return types.SimpleNamespace(url=url, position=position)


def _sku(**kw):
    kw.setdefault("id", uuid.uuid4())
    kw.setdefault("sku_code", "SKU-1")
    kw.setdefault("price", Decimal("25000"))
    kw.setdefault("original_price", None)
    kw.setdefault("stock", 10)
    kw.setdefault("variant_name", None)
    kw.setdefault("variant_value", None)
    kw.setdefault("images", [])
    return types.SimpleNamespace(**kw)


def _product(skus, attributes=None, category=None):
    return types.SimpleNamespace(
        id=uuid.uuid4(),
        name="Keripik Singkong Safiya",
        description="Keripik singkong renyah",
        images=[_img("https://cdn.example.id/keripik.jpg")],
        attributes=attributes,
        category=category,
        skus=skus,
    )


def _store():
    return types.SimpleNamespace(
        id=uuid.uuid4(),
        name="Safiya Food",
        description="Toko makanan ringan",
        logo_url=None,
        subscriber_id="safiyafood.jaringan-dagang.id",
    )


_ONDC_ATTRS = {
    "ondc": {
        "returnable": True,
        "cancellable": True,
        "time_to_ship": "PT30M",
        "statutory_reqs_packaged_commodities": {
            "manufacturer_or_packer_name": "PT Safiya Pangan",
            "net_quantity_or_measure_of_commodity_in_pkg": "200 g",
        },
        "statutory_reqs_prepackaged_food": {
            "brand_owner_FSSAI_license_no": "BPOM-MD-123456",
        },
    }
}


def _tag_codes(obj):
    return {t.code for t in (obj.tags or [])}


class TestItemStatutoryTagsEmitted:
    def test_sku_to_item_carries_statutory_groups(self):
        item = BecknCatalogBuilder._sku_to_item(
            _sku(), _product([_sku()], attributes=_ONDC_ATTRS)
        )
        codes = _tag_codes(item)
        assert ONDC_ORG_STATUTORY_PACKAGED_COMMODITIES in codes
        assert ONDC_ORG_STATUTORY_PREPACKAGED_FOOD in codes

    def test_statutory_values_are_passed_through(self):
        item = BecknCatalogBuilder._sku_to_item(
            _sku(), _product([_sku()], attributes=_ONDC_ATTRS)
        )
        pkg = next(
            t
            for t in item.tags
            if t.code == ONDC_ORG_STATUTORY_PACKAGED_COMMODITIES
        )
        kv = {e.code: e.value for e in pkg.list}
        assert kv["manufacturer_or_packer_name"] == "PT Safiya Pangan"
        assert kv["net_quantity_or_measure_of_commodity_in_pkg"] == "200 g"

    def test_variant_tags_still_present_alongside_ondc_tags(self):
        sku = _sku(variant_name="ukuran", variant_value="200g")
        item = BecknCatalogBuilder._sku_to_item(
            sku, _product([sku], attributes=_ONDC_ATTRS)
        )
        assert "variant" in _tag_codes(item)
        assert ONDC_ORG_STATUTORY_PACKAGED_COMMODITIES in _tag_codes(item)

    def test_no_ondc_attributes_means_no_statutory_tags(self):
        item = BecknCatalogBuilder._sku_to_item(_sku(), _product([_sku()]))
        assert ONDC_ORG_STATUTORY_PACKAGED_COMMODITIES not in _tag_codes(item)


class TestProviderFulfillmentAndPaymentTags:
    def test_provider_fulfillment_has_ondc_delivery_tag(self):
        prov = BecknCatalogBuilder.build_provider(
            _store(), [_product([_sku()], attributes=_ONDC_ATTRS)]
        )
        f0 = prov.fulfillments[0]
        codes = {t["code"] for t in (f0.get("tags") or [])}
        assert "delivery_terms" in codes

    def test_provider_payment_has_settlement_terms_tag(self):
        prov = BecknCatalogBuilder.build_provider(
            _store(), [_product([_sku()], attributes=_ONDC_ATTRS)]
        )
        p0 = prov.payments[0]
        codes = {t["code"] for t in (p0.get("tags") or [])}
        assert "settlement_terms" in codes
