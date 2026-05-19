"""Transform internal Product/SKU/ProductImage models into Beckn Catalog format.

Produces Beckn-compliant Catalog, Provider, and Item Pydantic models that can
be serialised into on_search / on_select responses.
"""

from __future__ import annotations

import sys
import os
from typing import Any, Sequence

# Make the beckn-protocol package importable
_proto_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "packages", "beckn-protocol")
)
if _proto_path not in sys.path:
    sys.path.insert(0, _proto_path)

from python import (
    Catalog,
    CategoryId,
    Descriptor,
    Fulfillment as BecknFulfillment,
    Image,
    Item,
    Payment as BecknPayment,
    PaymentCollectedBy,
    PaymentType,
    Price,
    Provider,
    Quantity,
    QuantityDetail,
    build_fulfillment_ondc_tags,
    build_item_statutory_tags,
    build_payment_settlement_tags,
    resolve_ondc_domain,
)

from app.models.product import Product
from app.models.sku import SKU
from app.models.store import Store


class BecknCatalogBuilder:
    """Builds Beckn Catalog objects from internal DB models."""

    # ------------------------------------------------------------------
    # Item-level helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_images(product: Product) -> list[Image]:
        """Convert ProductImage rows to Beckn Image objects."""
        images: list[Image] = []
        for img in sorted(product.images, key=lambda i: i.position):
            images.append(Image(url=img.url))
        return images

    @staticmethod
    def _build_sku_images(sku: SKU) -> list[Image]:
        """Convert SKUImage rows (per-variant gallery) to Beckn Image objects."""
        sku_images = getattr(sku, "images", None) or []
        return [Image(url=img.url) for img in sorted(sku_images, key=lambda i: i.position)]

    @staticmethod
    def _ondc_item_statutory_tags(product: Product) -> list:
        """Build ONDC item statutory tag groups from product.attributes.

        Packaged-F&B (ONDC:RET11) items carry statutory / packaged-commodity
        data under ``product.attributes["ondc"]`` with the two ONDC groups
        ``statutory_reqs_packaged_commodities`` /
        ``statutory_reqs_prepackaged_food`` (sub-key -> value maps). Absent
        or empty -> no tags (a store that hasn't filled statutory data
        simply emits none; we never fabricate values).
        """
        attrs = getattr(product, "attributes", None) or {}
        ondc = attrs.get("ondc") if isinstance(attrs, dict) else None
        if not isinstance(ondc, dict):
            return []
        return build_item_statutory_tags(
            packaged_commodities=ondc.get("statutory_reqs_packaged_commodities"),
            prepackaged_food=ondc.get("statutory_reqs_prepackaged_food"),
        )

    @staticmethod
    def _sku_to_item(sku: SKU, product: Product) -> Item:
        """Convert a single SKU (product variant) to a Beckn Item.

        Per-variant SKUImages take precedence over parent ProductImages so the
        buyer-side gallery swaps to the right photo when the user picks a size /
        flavour / color.
        """
        sku_imgs = BecknCatalogBuilder._build_sku_images(sku)
        product_imgs = BecknCatalogBuilder._build_images(product)
        images = sku_imgs or product_imgs

        # Keep descriptor.name as the parent product name so BAPs can group cleanly
        # by parent_item_id without inheriting a variant suffix. The variant info
        # is carried in `tags` (and visible on the variant picker).
        descriptor = Descriptor(
            name=product.name,
            short_desc=product.description[:200] if product.description else None,
            long_desc=product.description,
            images=images or None,
        )

        price = Price(
            currency="IDR",
            value=str(sku.price),
            listed_value=str(sku.original_price) if sku.original_price else None,
        )

        quantity = Quantity(
            available=QuantityDetail(count=sku.stock),
            maximum=QuantityDetail(count=min(sku.stock, 99)),
        )

        category_ids: list[str] | None = None
        if product.category and product.category.beckn_category_id:
            category_ids = [product.category.beckn_category_id]

        # Variant info as Beckn tags so the BAP can re-group + render variant
        # pickers, using the canonical flat {code,value} tag-list shape.
        item_tags: list = []
        if sku.variant_name or sku.variant_value:
            item_tags.append({
                "code": "variant",
                "list": [
                    {"code": "name", "value": sku.variant_name or ""},
                    {"code": "value", "value": sku.variant_value or ""},
                ],
            })
        # ONDC:RET11 item statutory / packaged-commodity tags (Task A2).
        item_tags.extend(BecknCatalogBuilder._ondc_item_statutory_tags(product))
        return Item(
            id=str(sku.id),
            parent_item_id=str(product.id),  # groups all SKUs of one product
            descriptor=descriptor,
            price=price,
            quantity=quantity,
            category_ids=category_ids,
            fulfillment_ids=["fulfillment-delivery"],
            payment_ids=["payment-prepaid"],
            matched=True,
            rateable=True,
            tags=item_tags or None,
        )

    # ------------------------------------------------------------------
    # Product -> list[Item]
    # ------------------------------------------------------------------

    @classmethod
    def product_to_items(cls, product: Product) -> list[Item]:
        """Convert a Product with its SKUs into a list of Beckn Items.

        Each SKU becomes its own Beckn Item (since they may have different
        prices and stock levels).
        """
        if not product.skus:
            return []
        return [cls._sku_to_item(sku, product) for sku in product.skus]

    # ------------------------------------------------------------------
    # Provider builder
    # ------------------------------------------------------------------

    @classmethod
    def build_provider(
        cls,
        store: Store,
        products: Sequence[Product],
    ) -> Provider:
        """Build a Beckn Provider from a Store and its products."""
        items: list[Item] = []
        categories_seen: dict[str, CategoryId] = {}

        for product in products:
            items.extend(cls.product_to_items(product))

            if product.category and product.category.beckn_category_id:
                cid = product.category.beckn_category_id
                if cid not in categories_seen:
                    categories_seen[cid] = CategoryId(
                        id=cid,
                        descriptor=Descriptor(name=product.category.name),
                    )

        provider_descriptor = Descriptor(
            name=store.name,
            short_desc=store.description,
            images=[Image(url=store.logo_url)] if store.logo_url else None,
        )

        # Resolve this store's ONDC domain (per-store; not hardcoded) so
        # downstream consumers know which ONDC sub-domain these tags are
        # scoped to. Safiya -> ONDC:RET11; unknown -> store-level default.
        ondc_domain = resolve_ondc_domain(store.subscriber_id)

        # ONDC:RET11 fulfillment delivery-terms tag (Task A2). DAP =
        # seller delivers to the buyer's named place, the typical retail
        # storefront-delivery incoterm.
        fulfillment_ondc_tags = [
            t.model_dump(exclude_none=True)
            for t in build_fulfillment_ondc_tags(incoterms="DAP")
        ]
        fulfillments: list[dict[str, Any]] = [
            BecknFulfillment(
                id="fulfillment-delivery",
                type="Delivery",
                tracking=True,
                tags=fulfillment_ondc_tags or None,
            ).model_dump(exclude_none=True),
        ]

        # ONDC:RET11 payment settlement-terms tag (Task A2): settle on
        # delivery, 1-day window, BAP finder fee — the ONDC RET defaults.
        payment_ondc_tags = [
            t.model_dump(exclude_none=True)
            for t in build_payment_settlement_tags(
                settlement_basis="delivery",
                settlement_window="P1D",
                buyer_app_finder_fee_type="percent",
                buyer_app_finder_fee_amount="3",
            )
        ]
        payments: list[dict[str, Any]] = [
            BecknPayment(
                id="payment-prepaid",
                type=PaymentType.PRE_FULFILLMENT,
                collected_by=PaymentCollectedBy.BPP,
                tags=payment_ondc_tags or None,
            ).model_dump(exclude_none=True),
        ]

        # Provider-level ONDC domain tag: carries the per-store resolved
        # ONDC sub-domain code (e.g. ONDC:RET11 for Safiya) alongside its
        # Beckn transport base, so the BAP can scope catalogue handling
        # without re-deriving it. Resolved, never hardcoded.
        provider_tags = [
            {
                "code": "@ondc/org/domain",
                "list": [
                    {"code": "domain_code", "value": ondc_domain.domain_code},
                    {"code": "beckn_domain", "value": ondc_domain.beckn_domain},
                ],
            }
        ]

        return Provider(
            # Use the canonical Beckn subscriber_id as Provider.id so BAPs can
            # mirror by toko identity, not by local UUID. Falls back to UUID
            # for stores without a subscriber_id yet.
            id=store.subscriber_id or str(store.id),
            descriptor=provider_descriptor,
            categories=list(categories_seen.values()) or None,
            items=items or None,
            fulfillments=fulfillments or None,
            payments=payments or None,
            rateable=True,
            tags=provider_tags,
        )

    # ------------------------------------------------------------------
    # Full catalog (on_search)
    # ------------------------------------------------------------------

    @classmethod
    def build_catalog(
        cls,
        stores_products: list[tuple[Store, Sequence[Product]]],
    ) -> Catalog:
        """Build a full Beckn Catalog from multiple stores and their products.

        Used in on_search responses.
        """
        providers: list[Provider] = []
        for store, products in stores_products:
            provider = cls.build_provider(store, products)
            if provider.items:
                providers.append(provider)

        return Catalog(
            descriptor=Descriptor(name="Jaringan Dagang BPP"),
            providers=providers or None,
        )

    # ------------------------------------------------------------------
    # Quote builder (on_select)
    # ------------------------------------------------------------------

    @classmethod
    def build_quote(
        cls,
        items_with_qty: list[tuple[SKU, int]],
        shipping_cost: int = 0,
    ) -> dict[str, Any]:
        """Build a Beckn Quote dict for the selected items.

        Returns a dict matching the Quote Pydantic model shape.
        """
        breakup: list[dict[str, Any]] = []
        total = 0

        for sku, qty in items_with_qty:
            line_total = int(sku.price) * qty
            total += line_total
            breakup.append(
                {
                    "title": f"Item: {sku.sku_code}",
                    "price": {"currency": "IDR", "value": str(line_total)},
                    "item": {
                        "id": str(sku.id),
                        "quantity": {"selected": {"count": qty}},
                        "price": {"currency": "IDR", "value": str(sku.price)},
                    },
                }
            )

        if shipping_cost > 0:
            total += shipping_cost
            breakup.append(
                {
                    "title": "Delivery Fee",
                    "price": {"currency": "IDR", "value": str(shipping_cost)},
                }
            )

        return {
            "price": {"currency": "IDR", "value": str(total)},
            "breakup": breakup,
            "ttl": "P1D",
        }
