"""Product CRUD business logic with PostgreSQL full-text search."""

from __future__ import annotations

import uuid
from typing import Any, Sequence

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.category import Category
from app.models.product import Product, ProductStatus
from app.models.product_image import ProductImage
from app.models.sku import SKU


async def list_products(
    db: AsyncSession,
    store_id: uuid.UUID,
    *,
    status: ProductStatus | None = None,
    category_id: uuid.UUID | None = None,
    offset: int = 0,
    limit: int = 50,
) -> Sequence[Product]:
    """List products for a store with optional filters."""
    stmt = (
        select(Product)
        .where(Product.store_id == store_id)
        .options(selectinload(Product.images), selectinload(Product.skus))
        .offset(offset)
        .limit(limit)
        .order_by(Product.created_at.desc())
    )
    if status is not None:
        stmt = stmt.where(Product.status == status)
    if category_id is not None:
        stmt = stmt.where(Product.category_id == category_id)

    result = await db.execute(stmt)
    return result.scalars().all()


async def get_product(
    db: AsyncSession,
    product_id: uuid.UUID,
) -> Product | None:
    """Fetch a single product with images and SKUs."""
    stmt = (
        select(Product)
        .where(Product.id == product_id)
        .options(
            selectinload(Product.images),
            selectinload(Product.skus),
            selectinload(Product.category),
        )
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_product(
    db: AsyncSession,
    store_id: uuid.UUID,
    data: dict[str, Any],
) -> Product:
    """Create a product with optional images and SKUs."""
    images_data = data.pop("images", [])
    skus_data = data.pop("skus", [])

    product = Product(store_id=store_id, **data)
    db.add(product)
    await db.flush()

    for idx, img in enumerate(images_data):
        db.add(
            ProductImage(
                product_id=product.id,
                url=img["url"],
                position=img.get("position", idx),
                is_primary=img.get("is_primary", idx == 0),
            )
        )

    for sku_data in skus_data:
        db.add(SKU(product_id=product.id, **sku_data))

    await db.flush()

    # Reload with relationships
    return await get_product(db, product.id)  # type: ignore[return-value]


async def update_product(
    db: AsyncSession,
    product_id: uuid.UUID,
    data: dict[str, Any],
) -> Product | None:
    """Update a product's scalar fields."""
    product = await get_product(db, product_id)
    if product is None:
        return None

    for key, value in data.items():
        if hasattr(product, key) and key not in ("id", "store_id", "created_at"):
            setattr(product, key, value)

    await db.flush()
    return await get_product(db, product_id)


async def delete_product(
    db: AsyncSession,
    product_id: uuid.UUID,
) -> bool:
    """Delete a product. Returns True if found and deleted."""
    product = await get_product(db, product_id)
    if product is None:
        return False
    await db.delete(product)
    await db.flush()
    return True


async def search_products(
    db: AsyncSession,
    store_id: uuid.UUID,
    *,
    keyword: str | None = None,
    category_id: uuid.UUID | None = None,
    limit: int = 50,
) -> Sequence[Product]:
    """Search products using PostgreSQL full-text search on name and description.

    Falls back to ILIKE when the search query is very short.
    """
    stmt = (
        select(Product)
        .where(
            and_(
                Product.store_id == store_id,
                Product.status == ProductStatus.ACTIVE,
            )
        )
        .options(selectinload(Product.images), selectinload(Product.skus))
        .limit(limit)
    )

    if category_id is not None:
        stmt = stmt.where(Product.category_id == category_id)

    if keyword:
        # Use PostgreSQL full-text search with to_tsvector / plainto_tsquery
        ts_vector = func.to_tsvector("indonesian", Product.name)
        ts_query = func.plainto_tsquery("indonesian", keyword)
        # Also search description, fall back to ILIKE for short terms
        ts_vector_desc = func.to_tsvector(
            "indonesian",
            func.coalesce(Product.description, ""),
        )
        fulltext_match = or_(
            ts_vector.op("@@")(ts_query),
            ts_vector_desc.op("@@")(ts_query),
        )
        ilike_match = or_(
            Product.name.ilike(f"%{keyword}%"),
            Product.description.ilike(f"%{keyword}%"),
        )
        stmt = stmt.where(or_(fulltext_match, ilike_match))

    result = await db.execute(stmt)
    return result.scalars().all()


async def search_products_all_stores(
    db: AsyncSession,
    *,
    keyword: str | None = None,
    category_beckn_id: str | None = None,
    limit: int = 50,
) -> Sequence[Product]:
    """Search active products across ALL stores (used by Beckn search)."""
    stmt = (
        select(Product)
        .where(Product.status == ProductStatus.ACTIVE)
        .options(
            selectinload(Product.images),
            selectinload(Product.skus),
            selectinload(Product.store),
            selectinload(Product.category),
        )
        .limit(limit)
    )

    if category_beckn_id is not None:
        stmt = stmt.join(Product.category).where(
            Category.beckn_category_id == category_beckn_id
        )

    if keyword:
        ts_vector = func.to_tsvector("indonesian", Product.name)
        ts_query = func.plainto_tsquery("indonesian", keyword)
        ts_vector_desc = func.to_tsvector(
            "indonesian",
            func.coalesce(Product.description, ""),
        )
        fulltext_match = or_(
            ts_vector.op("@@")(ts_query),
            ts_vector_desc.op("@@")(ts_query),
        )
        ilike_match = or_(
            Product.name.ilike(f"%{keyword}%"),
            Product.description.ilike(f"%{keyword}%"),
        )
        stmt = stmt.where(or_(fulltext_match, ilike_match))

    result = await db.execute(stmt)
    return result.scalars().all()
