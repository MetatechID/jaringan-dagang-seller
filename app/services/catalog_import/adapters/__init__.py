"""Source adapter registry.

Each adapter knows the column conventions of one marketplace export.
"""

from __future__ import annotations

from app.services.catalog_import.adapters.base import SourceAdapter
from app.services.catalog_import.adapters.bigseller import BigSellerAdapter
from app.services.catalog_import.adapters.shopee import ShopeeAdapter
from app.services.catalog_import.adapters.tokopedia import TokopediaAdapter
from app.services.catalog_import.adapters.lazada import LazadaAdapter
from app.services.catalog_import.adapters.generic import GenericAdapter

_REGISTRY: dict[str, SourceAdapter] = {
    "bigseller": BigSellerAdapter(),
    "shopee": ShopeeAdapter(),
    "tokopedia": TokopediaAdapter(),
    "lazada": LazadaAdapter(),
    "generic": GenericAdapter(),
}


def get_adapter(source: str) -> SourceAdapter:
    try:
        return _REGISTRY[source]
    except KeyError:
        raise ValueError(f"Unknown import source: {source!r}")


def list_adapters() -> list[SourceAdapter]:
    return list(_REGISTRY.values())


__all__ = ["SourceAdapter", "get_adapter", "list_adapters"]
