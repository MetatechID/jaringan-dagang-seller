"""Lazada bulk-product XLSX adapter.

Lazada's bulk template groups variations by 'SellerSku' (parent) with a
'_variationSku' suffix per variation.
"""

from __future__ import annotations


class LazadaAdapter:
    name = "lazada"
    display_name = "Lazada"
    file_extensions = (".xlsx",)
    hint = "Lazada Seller Center → Products → Manage Products → Bulk Edit → Download"
    logo_url = "https://www.google.com/s2/favicons?domain=lazada.co.id&sz=128"

    default_column_mapping = {
        "source_item_id": "SellerSku",
        "source_variant_id": "VariationSku",
        "name": "Name",
        "sku_code": "VariationSku",
        "price": "Price",
        "stock": "Quantity",
        "variant_name": "VariationName",
        "variant_value": "VariationValue",
        "image_url": "Image1",
        "weight_grams": "Package_weight",  # Lazada uses kg; normalizer converts
        "category_hint": "PrimaryCategory",
        "description": "Description",
    }

    def detect(self, headers: list[str]) -> float:
        markers = {"SellerSku", "VariationSku", "PrimaryCategory"}
        present = sum(1 for h in headers if h in markers)
        return present / max(len(markers), 1)
