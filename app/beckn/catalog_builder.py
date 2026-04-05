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
    def _sku_to_item(sku: SKU, product: Product) -> Item:
        """Convert a single SKU (product variant) to a Beckn Item."""
        images = BecknCatalogBuilder._build_images(product)

        item_name = product.name
        if sku.variant_name and sku.variant_value:
            item_name = f"{product.name} - {sku.variant_value}"

        descriptor = Descriptor(
            name=item_name,
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

        return Item(
            id=str(sku.id),
            descriptor=descriptor,
            price=price,
            quantity=quantity,
            category_ids=category_ids,
            fulfillment_ids=["fulfillment-delivery"],
            payment_ids=["payment-prepaid"],
            matched=True,
            rateable=True,
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

        fulfillments: list[dict[str, Any]] = [
            BecknFulfillment(
                id="fulfillment-delivery",
                type="Delivery",
                tracking=True,
            ).model_dump(exclude_none=True),
        ]

        payments: list[dict[str, Any]] = [
            BecknPayment(
                id="payment-prepaid",
                type=PaymentType.PRE_FULFILLMENT,
                collected_by=PaymentCollectedBy.BPP,
            ).model_dump(exclude_none=True),
        ]

        return Provider(
            id=str(store.id),
            descriptor=provider_descriptor,
            categories=list(categories_seen.values()) or None,
            items=items or None,
            fulfillments=fulfillments or None,
            payments=payments or None,
            rateable=True,
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
