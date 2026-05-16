"""Shopee mass-upload XLSX adapter.

Shopee's mass-upload template lists each variation as a separate row, all
sharing 'Parent SKU' / product name. Stock and price are per-variation.
"""

from __future__ import annotations


class ShopeeAdapter:
    name = "shopee"
    display_name = "Shopee"
    file_extensions = (".xlsx",)
    hint = "Shopee Seller Centre → Products → Mass Upload → Download"

    default_column_mapping = {
        "source_item_id": "Parent SKU",
        "source_variant_id": "Variation SKU",
        "name": "Product Name",
        "sku_code": "Variation SKU",
        "price": "Price",
        "stock": "Stock",
        "variant_name": "Variation Name",
        "variant_value": "Option",
        "image_url": "Cover Image",
        "weight_grams": "Weight",
        "category_hint": "Category",
        "description": "Product Description",
    }

    def detect(self, headers: list[str]) -> float:
        markers = {"Parent SKU", "Variation SKU", "Variation Name"}
        present = sum(1 for h in headers if h in markers)
        return present / max(len(markers), 1)
