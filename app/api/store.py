"""Internal REST API for store settings (seller dashboard)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.store import Store

router = APIRouter(prefix="/store", tags=["store"])


class StoreUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    logo_url: str | None = None
    domain: str | None = None
    city: str | None = None
    status: str | None = None


@router.get("")
async def get_store(
    db: AsyncSession = Depends(get_db),
):
    """Get the current store settings (first active store)."""
    result = await db.execute(
        select(Store).where(Store.status == "active").limit(1)
    )
    store = result.scalar_one_or_none()
    if store is None:
        raise HTTPException(status_code=404, detail="No active store found")
    return {"data": _serialize(store)}


@router.put("")
async def update_store(
    body: StoreUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update store settings."""
    result = await db.execute(
        select(Store).where(Store.status == "active").limit(1)
    )
    store = result.scalar_one_or_none()
    if store is None:
        raise HTTPException(status_code=404, detail="No active store found")

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if hasattr(store, key):
            setattr(store, key, value)

    await db.flush()
    return {"data": _serialize(store)}


# ------------------------------------------------------------------
# Serialisation helper
# ------------------------------------------------------------------


def _serialize(store: Store) -> dict[str, Any]:
    return {
        "id": str(store.id),
        "subscriber_id": store.subscriber_id,
        "subscriber_url": store.subscriber_url,
        "name": store.name,
        "description": store.description,
        "logo_url": store.logo_url,
        "domain": store.domain,
        "city": store.city,
        "signing_public_key": store.signing_public_key,
        "status": store.status,
        "created_at": store.created_at.isoformat() if store.created_at else None,
        "updated_at": store.updated_at.isoformat() if store.updated_at else None,
    }
