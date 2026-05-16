"""BigSeller XLSX export adapter.

BigSeller's bulk product export uses a parent-product row pattern: each variant
gets its own row, all sharing a 'Product ID' / 'Master SKU' that we treat as
the parent group key. Variant attribute lives in 'Variation Name'.
"""

from __future__ import annotations


class BigSellerAdapter:
    name = "bigseller"
    display_name = "BigSeller"
    file_extensions = (".xlsx",)
    hint = "BigSeller → Products → Bulk Export → XLSX"

    default_column_mapping = {
        "source_item_id": "Product ID",
        "source_variant_id": "Variation ID",
        "name": "Product Name",
        "sku_code": "SKU",
        "price": "Selling Price",
        "stock": "Stock",
        "variant_name": "Variation Type",
        "variant_value": "Variation Name",
        "image_url": "Image URL",
        "weight_grams": "Weight (g)",
        "category_hint": "Category",
        "description": "Description",
    }

    def detect(self, headers: list[str]) -> float:
        markers = {"Product ID", "Variation ID", "Selling Price"}
        present = sum(1 for h in headers if h in markers)
        return present / max(len(markers), 1)
