"""Tokopedia XLSX export adapter.

Tokopedia exports use Indonesian column headers. Variants are listed per-row
with a shared 'Kode Produk Induk' (Parent Product Code).
"""

from __future__ import annotations


class TokopediaAdapter:
    name = "tokopedia"
    display_name = "Tokopedia"
    file_extensions = (".xlsx",)
    hint = "Tokopedia Seller → Produk → Export Produk → Unduh"

    default_column_mapping = {
        "source_item_id": "Kode Produk Induk",
        "source_variant_id": "Kode Produk Varian",
        "name": "Nama Produk",
        "sku_code": "SKU",
        "price": "Harga",
        "stock": "Stok",
        "variant_name": "Tipe Varian",
        "variant_value": "Nama Varian",
        "image_url": "URL Gambar",
        "weight_grams": "Berat (g)",
        "category_hint": "Kategori",
        "description": "Deskripsi",
    }

    def detect(self, headers: list[str]) -> float:
        markers = {"Nama Produk", "Kode Produk Induk", "Harga"}
        present = sum(1 for h in headers if h in markers)
        return present / max(len(markers), 1)
