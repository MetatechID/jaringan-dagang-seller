"""Internal REST API for product CRUD (seller dashboard)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.product import ProductStatus
from app.services import catalog_service

router = APIRouter(prefix="/products", tags=["products"])


# ------------------------------------------------------------------
# Pydantic schemas for request / response
# ------------------------------------------------------------------


class ImageCreate(BaseModel):
    url: str
    position: int = 0
    is_primary: bool = False


class SKUCreate(BaseModel):
    variant_name: str | None = None
    variant_value: str | None = None
    sku_code: str
    price: float
    original_price: float | None = None
    stock: int = 0
    weight_grams: int | None = None


class ProductCreate(BaseModel):
    name: str
    description: str | None = None
    sku: str | None = None
    category_id: uuid.UUID | None = None
    status: ProductStatus = ProductStatus.DRAFT
    attributes: dict[str, Any] | None = None
    images: list[ImageCreate] = Field(default_factory=list)
    skus: list[SKUCreate] = Field(default_factory=list)


class ProductUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    sku: str | None = None
    category_id: uuid.UUID | None = None
    status: ProductStatus | None = None
    attributes: dict[str, Any] | None = None


class ProductOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    store_id: uuid.UUID
    name: str
    description: str | None = None
    sku: str | None = None
    status: ProductStatus


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

# NOTE: In production you would extract store_id from an auth token.
# For now it is passed as a query parameter for simplicity.

DEMO_STORE_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


@router.get("")
async def list_products(
    store_id: uuid.UUID = Query(default=DEMO_STORE_ID),
    status: ProductStatus | None = None,
    category_id: uuid.UUID | None = None,
    offset: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """List products for a store."""
    products = await catalog_service.list_products(
        db,
        store_id,
        status=status,
        category_id=category_id,
        offset=offset,
        limit=limit,
    )
    return {"data": [_serialize(p) for p in products]}


@router.post("", status_code=201)
async def create_product(
    body: ProductCreate,
    store_id: uuid.UUID = Query(default=DEMO_STORE_ID),
    db: AsyncSession = Depends(get_db),
):
    """Create a new product with optional images and SKUs."""
    data = body.model_dump()
    product = await catalog_service.create_product(db, store_id, data)
    return {"data": _serialize(product)}


@router.get("/{product_id}")
async def get_product(
    product_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a single product by ID."""
    product = await catalog_service.get_product(db, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"data": _serialize(product)}


@router.put("/{product_id}")
async def update_product(
    product_id: uuid.UUID,
    body: ProductUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a product's fields."""
    data = body.model_dump(exclude_unset=True)
    product = await catalog_service.update_product(db, product_id, data)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"data": _serialize(product)}


@router.delete("/{product_id}", status_code=204)
async def delete_product(
    product_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Delete a product."""
    deleted = await catalog_service.delete_product(db, product_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Product not found")
    return None


# ------------------------------------------------------------------
# Serialisation helper
# ------------------------------------------------------------------


def _serialize(product) -> dict[str, Any]:
    """Serialize a Product ORM object to a dict."""
    images = []
    if product.images:
        images = [
            {
                "id": str(img.id),
                "url": img.url,
                "position": img.position,
                "is_primary": img.is_primary,
            }
            for img in product.images
        ]

    skus = []
    if product.skus:
        skus = [
            {
                "id": str(s.id),
                "variant_name": s.variant_name,
                "variant_value": s.variant_value,
                "sku_code": s.sku_code,
                "price": float(s.price),
                "original_price": float(s.original_price) if s.original_price else None,
                "stock": s.stock,
                "weight_grams": s.weight_grams,
            }
            for s in product.skus
        ]

    return {
        "id": str(product.id),
        "store_id": str(product.store_id),
        "name": product.name,
        "description": product.description,
        "sku": product.sku,
        "status": product.status.value if product.status else None,
        "attributes": product.attributes,
        "category_id": str(product.category_id) if product.category_id else None,
        "images": images,
        "skus": skus,
        "created_at": product.created_at.isoformat() if product.created_at else None,
        "updated_at": product.updated_at.isoformat() if product.updated_at else None,
    }
