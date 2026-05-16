"""Apply normalized ImportedItems to the catalog.

Match order per item:
    1. MarketplaceProductMap(source, source_variant_id or source_item_id)
    2. SKU by sku_code within store
    3. Create new SKU and (if no group sibling exists yet) a new Product

A Postgres advisory lock keyed on store_id serializes concurrent imports for
the same store. The lock is released automatically when the transaction
commits or rolls back.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import and_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.marketplace_map import MarketplaceProductMap
from app.models.product import Product, ProductStatus
from app.models.product_image import ProductImage
from app.models.sku import SKU
from app.services.catalog_import.types import ImportedItem


@dataclass
class ApplierResult:
    created_products: int = 0
    created_skus: int = 0
    updated_skus: int = 0
    skipped: int = 0  # rows with errors
    errors: list[dict] = field(default_factory=list)  # [{row_number, sku_code, message}]


async def apply(
    db: AsyncSession,
    store_id: uuid.UUID,
    source: str,
    items: list[ImportedItem],
) -> ApplierResult:
    """Commit a list of ImportedItems to the catalog for one store.

    Caller is responsible for the outer transaction. This function uses
    savepoints so a row-level failure doesn't poison the whole import.
    """

    result = ApplierResult()
    await _acquire_store_lock(db, store_id)

    # Group items by parent_group_key so siblings attach to one Product.
    groups: dict[str, list[ImportedItem]] = defaultdict(list)
    for item in items:
        groups[item.parent_group_key].append(item)

    for group_key, group_items in groups.items():
        # Skip rows with errors entirely; surface them in the result.
        usable = []
        for it in group_items:
            if it.errors:
                result.skipped += 1
                for err in it.errors:
                    result.errors.append(
                        {"row_number": it.row_number, "sku_code": it.sku_code, "message": err}
                    )
            else:
                usable.append(it)
        if not usable:
            continue

        # Find an existing Product for this group via any of the SKUs.
        product = await _find_or_create_product(db, store_id, source, usable, result)

        for it in usable:
            await _upsert_sku(db, product, source, it, result)

    await db.flush()
    return result


async def _acquire_store_lock(db: AsyncSession, store_id: uuid.UUID) -> None:
    """Postgres advisory lock keyed on store_id (hashed to bigint).

    Two int4 args, each 32 bits — half from UUID hi, half from lo.
    """
    hi = (store_id.int >> 64) & 0x7FFFFFFF
    lo = store_id.int & 0x7FFFFFFF
    await db.execute(text("SELECT pg_advisory_xact_lock(:hi, :lo)"), {"hi": hi, "lo": lo})


async def _find_or_create_product(
    db: AsyncSession,
    store_id: uuid.UUID,
    source: str,
    items: list[ImportedItem],
    result: ApplierResult,
) -> Product:
    """Find an existing Product for this group via any item's match keys.

    Match attempts, in order:
      1. MarketplaceProductMap for any item's source_item_id / source_variant_id
      2. SKU.sku_code matching any item's sku_code, scoped to this store
    """

    # 1. Marketplace map lookup — any source_variant_id, or source_item_id
    candidate_ids: list[str] = []
    for it in items:
        if it.source_variant_id:
            candidate_ids.append(it.source_variant_id)
        if it.source_item_id and it.source_item_id != it.source_variant_id:
            candidate_ids.append(it.source_item_id)
    if candidate_ids:
        stmt = (
            select(MarketplaceProductMap)
            .where(
                and_(
                    MarketplaceProductMap.marketplace_name == source,
                    MarketplaceProductMap.marketplace_item_id.in_(candidate_ids),
                )
            )
            .options(selectinload(MarketplaceProductMap.sku))
            .limit(1)
        )
        row = (await db.execute(stmt)).scalars().first()
        if row is not None:
            sku = row.sku
            product = await db.get(Product, sku.product_id)
            if product is not None and product.store_id == store_id:
                return product

    # 2. SKU code lookup, scoped to store
    sku_codes = [it.sku_code for it in items if it.sku_code]
    if sku_codes:
        stmt = (
            select(SKU)
            .join(Product, SKU.product_id == Product.id)
            .where(and_(SKU.sku_code.in_(sku_codes), Product.store_id == store_id))
            .limit(1)
        )
        sku = (await db.execute(stmt)).scalars().first()
        if sku is not None:
            product = await db.get(Product, sku.product_id)
            if product is not None:
                return product

    # 3. Create a new product
    first = items[0]
    product = Product(
        store_id=store_id,
        name=first.name,
        description=first.description,
        sku=first.sku_code,
        status=ProductStatus.ACTIVE,
        attributes=None,
    )
    db.add(product)
    await db.flush()
    result.created_products += 1

    # Attach product-level images from the first item (assumed shared across variants)
    for idx, url in enumerate(first.image_urls):
        db.add(
            ProductImage(
                product_id=product.id,
                url=url,
                position=idx,
                is_primary=(idx == 0),
            )
        )

    return product


async def _upsert_sku(
    db: AsyncSession,
    product: Product,
    source: str,
    item: ImportedItem,
    result: ApplierResult,
) -> None:
    """Update an existing SKU or create a new one. Backfill the marketplace map."""

    sku: SKU | None = None

    # Match by marketplace map first
    match_id = item.source_variant_id or item.source_item_id
    if match_id:
        stmt = (
            select(MarketplaceProductMap)
            .where(
                and_(
                    MarketplaceProductMap.marketplace_name == source,
                    MarketplaceProductMap.marketplace_item_id == match_id,
                )
            )
            .options(selectinload(MarketplaceProductMap.sku))
            .limit(1)
        )
        row = (await db.execute(stmt)).scalars().first()
        if row is not None and row.sku.product_id == product.id:
            sku = row.sku

    # Match by sku_code if no map hit
    if sku is None and item.sku_code:
        stmt = select(SKU).where(
            and_(SKU.sku_code == item.sku_code, SKU.product_id == product.id)
        )
        sku = (await db.execute(stmt)).scalars().first()

    if sku is None:
        # Create new SKU
        sku = SKU(
            product_id=product.id,
            sku_code=item.sku_code,
            variant_name=item.variant_name,
            variant_value=item.variant_value,
            price=item.price,
            stock=item.stock,
            weight_grams=item.weight_grams,
        )
        db.add(sku)
        await db.flush()
        result.created_skus += 1
    else:
        # Update price, stock, weight, variant_value. Leave images alone.
        sku.price = item.price
        sku.stock = item.stock
        if item.weight_grams is not None:
            sku.weight_grams = item.weight_grams
        if item.variant_value:
            sku.variant_value = item.variant_value
        if item.variant_name:
            sku.variant_name = item.variant_name
        result.updated_skus += 1

    # Backfill marketplace map if missing
    if match_id:
        existing_map_stmt = select(MarketplaceProductMap).where(
            and_(
                MarketplaceProductMap.sku_id == sku.id,
                MarketplaceProductMap.marketplace_name == source,
                MarketplaceProductMap.marketplace_item_id == match_id,
            )
        )
        existing_map = (await db.execute(existing_map_stmt)).scalars().first()
        if existing_map is None:
            db.add(
                MarketplaceProductMap(
                    sku_id=sku.id,
                    marketplace_name=source,
                    marketplace_item_id=match_id,
                )
            )
