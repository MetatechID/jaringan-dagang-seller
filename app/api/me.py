"""Auth + membership APIs.

GET  /api/me                            current user profile
GET  /api/me/stores                     stores I can access (super admin = all)
GET  /api/stores/{store_id}/members     list members of a store
POST /api/stores/{store_id}/members     invite by email + role (owner only)
DELETE /api/stores/{store_id}/members/{membership_id}   revoke (owner only)
"""

from __future__ import annotations

import logging
import traceback
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from app.auth.deps import (
    can_access_store,
    get_current_user,
    require_store_owner,
)
from app.database import get_db
from app.models.store import Store
from app.models.store_membership import StoreMembership, StoreRole
from app.models.user import User

router = APIRouter(tags=["auth"])


def _serialize_user(u: User) -> dict[str, Any]:
    return {
        "id": str(u.id),
        "email": u.email,
        "display_name": u.display_name,
        "photo_url": u.photo_url,
        "is_super_admin": u.is_super_admin,
    }


def _serialize_store(s: Store) -> dict[str, Any]:
    return {
        "id": str(s.id),
        "subscriber_id": s.subscriber_id,
        "name": s.name,
        "description": s.description,
        "logo_url": s.logo_url,
        "domain": s.domain,
        "city": s.city,
        "status": s.status,
    }


def _serialize_member(m: StoreMembership, u: User | None) -> dict[str, Any]:
    return {
        "membership_id": str(m.id),
        "store_id": str(m.store_id),
        "email": m.invited_email,
        "role": m.role.value if isinstance(m.role, StoreRole) else m.role,
        "accepted_at": m.accepted_at.isoformat() if m.accepted_at else None,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "pending": u is None,
        "user": _serialize_user(u) if u else None,
    }


# ------------------------------------------------------------------
# Current user
# ------------------------------------------------------------------


@router.get("/me")
async def get_me(user: User = Depends(get_current_user)) -> dict[str, Any]:
    try:
        return {"data": _serialize_user(user)}
    except Exception as e:
        logger.exception("/api/me failed")
        raise HTTPException(500, f"{type(e).__name__}: {e}\n{traceback.format_exc()[-1500:]}")


@router.get("/me/stores")
async def get_my_stores(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Stores this user can access. Super admins see every active store."""
    try:
        if user.is_super_admin:
            stores = (
                await db.execute(
                    select(Store).where(Store.status == "active").order_by(Store.name)
                )
            ).scalars().all()
            return {
                "data": [
                    {**_serialize_store(s), "role": "super_admin", "membership_id": None}
                    for s in stores
                ]
            }

        rows = (
            await db.execute(
                select(StoreMembership, Store)
                .join(Store, Store.id == StoreMembership.store_id)
                .where(StoreMembership.user_id == user.id)
                .where(Store.status == "active")
                .order_by(Store.name)
            )
        ).all()
        return {
            "data": [
                {
                    **_serialize_store(s),
                    "role": m.role.value if isinstance(m.role, StoreRole) else m.role,
                    "membership_id": str(m.id),
                }
                for (m, s) in rows
            ]
        }
    except Exception as e:
        logger.exception("/api/me/stores failed")
        raise HTTPException(500, f"{type(e).__name__}: {e}\n{traceback.format_exc()[-1800:]}")


# ------------------------------------------------------------------
# Team management (per-store)
# ------------------------------------------------------------------


class InviteBody(BaseModel):
    email: EmailStr
    role: StoreRole = StoreRole.STAFF


@router.get("/stores/{store_id}/members")
async def list_members(
    store_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        sid = uuid.UUID(store_id)
    except (ValueError, TypeError):
        raise HTTPException(400, "store_id must be a UUID")
    if not await can_access_store(db, user, sid):
        raise HTTPException(403, "no access to this store")
    # Join membership → user (LEFT OUTER for pending invites)
    rows = (
        await db.execute(
            select(StoreMembership, User)
            .outerjoin(User, User.id == StoreMembership.user_id)
            .where(StoreMembership.store_id == sid)
            .order_by(StoreMembership.created_at)
        )
    ).all()
    return {"data": [_serialize_member(m, u) for (m, u) in rows]}


@router.post("/stores/{store_id}/members", status_code=201)
async def invite_member(
    store_id: str,
    body: InviteBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Owner-only: invite by email. If the email already has a user row, link
    immediately. Otherwise create a pending invite; first sign-in will claim it.
    """
    try:
        sid = uuid.UUID(store_id)
    except (ValueError, TypeError):
        raise HTTPException(400, "store_id must be a UUID")
    if not user.is_super_admin:
        if not await can_access_store(db, user, sid, min_role=StoreRole.OWNER):
            raise HTTPException(403, "store owner only")

    email_lc = body.email.lower()

    # Dedupe by (email, store_id)
    existing = (
        await db.execute(
            select(StoreMembership)
            .where(StoreMembership.store_id == sid)
            .where(StoreMembership.invited_email == email_lc)
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.role = body.role
        await db.commit()
        return {"data": _serialize_member(existing, None), "note": "updated existing"}

    target_user = (
        await db.execute(select(User).where(User.email == email_lc))
    ).scalar_one_or_none()

    from datetime import datetime, timezone
    m = StoreMembership(
        user_id=target_user.id if target_user else None,
        invited_email=email_lc,
        store_id=sid,
        role=body.role,
        invited_by_user_id=user.id,
        accepted_at=datetime.now(timezone.utc) if target_user else None,
    )
    db.add(m)
    await db.commit()
    await db.refresh(m)
    return {"data": _serialize_member(m, target_user)}


@router.delete("/stores/{store_id}/members/{membership_id}", status_code=204)
async def revoke_member(
    store_id: str,
    membership_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        sid = uuid.UUID(store_id)
        mid = uuid.UUID(membership_id)
    except (ValueError, TypeError):
        raise HTTPException(400, "store_id and membership_id must be UUIDs")
    if not user.is_super_admin:
        if not await can_access_store(db, user, sid, min_role=StoreRole.OWNER):
            raise HTTPException(403, "store owner only")
    m = (
        await db.execute(
            select(StoreMembership)
            .where(StoreMembership.id == mid)
            .where(StoreMembership.store_id == sid)
        )
    ).scalar_one_or_none()
    if m is None:
        raise HTTPException(404, "membership not found")
    # Prevent removing the last owner
    if m.role == StoreRole.OWNER:
        owners = (
            await db.execute(
                select(StoreMembership)
                .where(StoreMembership.store_id == sid)
                .where(StoreMembership.role == StoreRole.OWNER)
            )
        ).scalars().all()
        if len(owners) <= 1:
            raise HTTPException(400, "cannot remove the last owner")
    await db.delete(m)
    await db.commit()
    return None
