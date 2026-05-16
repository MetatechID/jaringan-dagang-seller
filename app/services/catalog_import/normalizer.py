"""Normalize raw header-keyed rows into ImportedItem instances.

This is the layer that applies a column mapping, parses Indonesian-style
currency, splits multi-image cells, and surfaces row-level warnings/errors.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from app.services.catalog_import.types import (
    ImportedItem,
    REQUIRED_FIELDS,
)


def normalize(
    rows: list[dict[str, Any]],
    column_mapping: dict[str, str],
    source_name: str,
) -> tuple[list[ImportedItem], dict[str, int]]:
    """Apply column_mapping to every row, return items + summary stats.

    Items always come back even if they have errors — the UI surfaces them
    as 🔴 badges and blocks the Confirm button. Duplicate sku_code within a
    single file is detected here.
    """

    items: list[ImportedItem] = []
    seen_sku_codes: dict[str, int] = {}  # sku_code → row_number it first appeared
    is_lazada = source_name == "lazada"

    for idx, row in enumerate(rows, start=2):  # row 1 is header
        item = _normalize_row(row, column_mapping, idx, is_lazada=is_lazada)
        prior = seen_sku_codes.get(item.sku_code)
        if prior is not None and item.sku_code:
            item.errors.append(
                f"Duplicate SKU '{item.sku_code}' (first seen on row {prior})"
            )
        elif item.sku_code:
            seen_sku_codes[item.sku_code] = idx
        items.append(item)

    summary = _summarize(items)
    return items, summary


def _normalize_row(
    row: dict[str, Any],
    mapping: dict[str, str],
    row_number: int,
    *,
    is_lazada: bool,
) -> ImportedItem:
    raw = {field: row.get(src_col) for field, src_col in mapping.items()}

    name = _str_or_none(raw.get("name")) or ""
    sku_code = _str_or_none(raw.get("sku_code")) or ""

    price, price_err = _parse_money(raw.get("price"))
    stock, stock_warn = _parse_stock(raw.get("stock"))
    weight_grams = _parse_weight(raw.get("weight_grams"), is_lazada=is_lazada)
    image_urls = _split_images(raw.get("image_url"))

    source_item_id = _str_or_none(raw.get("source_item_id")) or sku_code
    source_variant_id = _str_or_none(raw.get("source_variant_id"))
    parent_group_key = source_item_id  # variants share the parent product ID

    warnings: list[str] = []
    errors: list[str] = []

    for required in REQUIRED_FIELDS:
        value = {"name": name, "sku_code": sku_code, "price": price, "stock": stock}[required]
        if required == "stock":
            continue  # stock has a fallback to 0; warning issued separately
        if required == "price":
            if value is None:
                errors.append("Missing 'price'")
            continue
        if not value:
            errors.append(f"Missing '{required}'")

    if price_err:
        errors.append(price_err)
    if stock_warn:
        warnings.append(stock_warn)
    if price is not None and price == 0:
        warnings.append("Price is 0")

    return ImportedItem(
        source_item_id=source_item_id or sku_code or f"row-{row_number}",
        source_variant_id=source_variant_id,
        parent_group_key=parent_group_key or sku_code or f"row-{row_number}",
        name=name,
        sku_code=sku_code,
        price=price if price is not None else Decimal(0),
        stock=stock,
        variant_name=_str_or_none(raw.get("variant_name")),
        variant_value=_str_or_none(raw.get("variant_value")),
        image_urls=image_urls,
        weight_grams=weight_grams,
        category_hint=_str_or_none(raw.get("category_hint")),
        description=_str_or_none(raw.get("description")),
        warnings=warnings,
        errors=errors,
        row_number=row_number,
    )


_MONEY_STRIP = re.compile(r"[^\d.,\-]")


def _parse_money(v: Any) -> tuple[Decimal | None, str | None]:
    """Parse Indonesian/global money formats into Decimal rupiah (integer).

    Handles: 'Rp 12.500', '12.500', '12,500.00', '12500', 12500, Decimal('12500').
    Returns (None, error_message) on failure.
    """
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return None, None
    if isinstance(v, (int, Decimal)):
        try:
            return Decimal(v).quantize(Decimal("1")), None
        except (InvalidOperation, ValueError):
            return None, f"Could not parse price {v!r}"
    if isinstance(v, float):
        return Decimal(str(round(v))), None
    s = str(v)
    stripped = _MONEY_STRIP.sub("", s)
    if stripped == "":
        return None, f"Could not parse price {v!r}"
    # Both . and , present: assume , is decimal sep if rightmost; else . is decimal
    if "," in stripped and "." in stripped:
        if stripped.rfind(",") > stripped.rfind("."):
            stripped = stripped.replace(".", "").replace(",", ".")
        else:
            stripped = stripped.replace(",", "")
    elif "," in stripped:
        # Indonesian thousands sep can be , — but if it appears with 3-digit groups
        # treat as thousands; if 1-2 digits after, treat as decimal.
        last = stripped.rsplit(",", 1)[-1]
        if len(last) == 3 and stripped.count(",") >= 1 and "." not in stripped:
            stripped = stripped.replace(",", "")
        else:
            stripped = stripped.replace(",", ".")
    elif "." in stripped:
        # Indonesian Rp uses '.' as thousands separator. If multiple dots or
        # right-side group is 3 chars, treat as thousands.
        parts = stripped.split(".")
        if len(parts) > 2 or (len(parts) == 2 and len(parts[1]) == 3):
            stripped = stripped.replace(".", "")
        # else leave (e.g. "12.5" → 12.5)
    try:
        d = Decimal(stripped)
    except InvalidOperation:
        return None, f"Could not parse price {v!r}"
    return d.quantize(Decimal("1")), None  # round to integer rupiah


def _parse_stock(v: Any) -> tuple[int, str | None]:
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return 0, "Stock missing; treated as 0"
    try:
        if isinstance(v, str):
            v = v.strip().replace(",", "").replace(".", "")
        return int(v), None
    except (ValueError, TypeError):
        return 0, f"Stock {v!r} is not a number; treated as 0"


def _parse_weight(v: Any, *, is_lazada: bool) -> int | None:
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return None
    try:
        f = float(str(v).replace(",", "."))
    except (ValueError, TypeError):
        return None
    if is_lazada:
        # Lazada Package_weight is kg
        return int(round(f * 1000))
    return int(round(f))


_IMAGE_SPLIT = re.compile(r"[,;|\s]+")


def _split_images(v: Any) -> list[str]:
    if v is None:
        return []
    s = str(v).strip()
    if not s:
        return []
    candidates = _IMAGE_SPLIT.split(s)
    return [c for c in candidates if c.startswith(("http://", "https://"))]


def _str_or_none(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _summarize(items: list[ImportedItem]) -> dict[str, int]:
    """Mutually-exclusive buckets so new+update+warn+error == total.

    new vs update can't be known here without DB lookup — the applier
    distinguishes them. Preview shows 'new' for any non-warn, non-error row.
    """
    new = update = warn = error = 0
    for it in items:
        if it.errors:
            error += 1
        elif it.warnings:
            warn += 1
        else:
            new += 1
    return {"new": new, "update": update, "warn": warn, "error": error, "total": len(items)}
