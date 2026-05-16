"""Canonical types shared across the catalog-import pipeline.

ImportedItem is the intermediate representation that sits between
source-specific adapters (BigSeller, Shopee, ...) and the applier.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass
class ImportedItem:
    """One row of an import, normalized to Jaringan's catalog shape.

    Variants of the same product share parent_group_key; the applier uses
    this to attach SKUs to a single Product row.
    """

    source_item_id: str
    source_variant_id: str | None
    parent_group_key: str
    name: str
    sku_code: str
    price: Decimal
    stock: int
    variant_name: str | None = None
    variant_value: str | None = None
    image_urls: list[str] = field(default_factory=list)
    weight_grams: int | None = None
    category_hint: str | None = None
    description: str | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    row_number: int = 0  # 1-indexed source row, for error messages

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_item_id": self.source_item_id,
            "source_variant_id": self.source_variant_id,
            "parent_group_key": self.parent_group_key,
            "name": self.name,
            "sku_code": self.sku_code,
            "price": str(self.price),
            "stock": self.stock,
            "variant_name": self.variant_name,
            "variant_value": self.variant_value,
            "image_urls": list(self.image_urls),
            "weight_grams": self.weight_grams,
            "category_hint": self.category_hint,
            "description": self.description,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "row_number": self.row_number,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ImportedItem":
        return cls(
            source_item_id=d["source_item_id"],
            source_variant_id=d.get("source_variant_id"),
            parent_group_key=d["parent_group_key"],
            name=d["name"],
            sku_code=d["sku_code"],
            price=Decimal(d["price"]),
            stock=int(d["stock"]),
            variant_name=d.get("variant_name"),
            variant_value=d.get("variant_value"),
            image_urls=list(d.get("image_urls", [])),
            weight_grams=d.get("weight_grams"),
            category_hint=d.get("category_hint"),
            description=d.get("description"),
            warnings=list(d.get("warnings", [])),
            errors=list(d.get("errors", [])),
            row_number=d.get("row_number", 0),
        )


# Canonical field keys used in column_mapping. The wizard UI surfaces these as
# the left-hand column of the mapping table.
CANONICAL_FIELDS = (
    "source_item_id",
    "source_variant_id",
    "name",
    "sku_code",
    "price",
    "stock",
    "variant_name",
    "variant_value",
    "image_url",   # may be comma-separated in source cell
    "weight_grams",
    "category_hint",
    "description",
)

REQUIRED_FIELDS = ("name", "sku_code", "price", "stock")
