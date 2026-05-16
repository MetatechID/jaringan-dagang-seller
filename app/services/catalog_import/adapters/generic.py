"""Generic CSV/XLSX adapter — identity mapping.

The 'Generic' template uses Jaringan's canonical field names directly as
column headers. Used by tokos who don't have a marketplace export and just
want to type into a spreadsheet.
"""

from __future__ import annotations


class GenericAdapter:
    name = "generic"
    display_name = "Generic (CSV/XLSX)"
    file_extensions = (".csv", ".xlsx")
    hint = "Download the starter template, fill it in, upload"
    # Generic has no brand; the UI falls back to a spreadsheet icon when this is empty.
    logo_url = ""

    default_column_mapping = {
        "source_item_id": "Parent ID",
        "source_variant_id": "Variant ID",
        "name": "Name",
        "sku_code": "SKU",
        "price": "Price",
        "stock": "Stock",
        "variant_name": "Variant Name",
        "variant_value": "Variant Value",
        "image_url": "Image URL",
        "weight_grams": "Weight (g)",
        "category_hint": "Category",
        "description": "Description",
    }

    def detect(self, headers: list[str]) -> float:
        markers = {"Name", "SKU", "Price", "Stock"}
        present = sum(1 for h in headers if h in markers)
        return present / max(len(markers), 1)
