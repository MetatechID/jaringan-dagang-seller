"""FastAPI dependencies for authentication + ACL.

Usage:
    @router.get("/foo")
    async def foo(user: User = Depends(get_current_user)):
        ...

    @router.get("/store-only")
    async def store_only(
        store_id: str,
        user: User = Depends(require_store_access),  # raises 403 if no access
    ): ...
"""

from __future__ import annotations

import logging
import os
import traceback
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.firebase import verify_id_token
from app.database import get_db
from app.models.user import User
from app.models.store_membership import StoreMembership, StoreRole

logger = logging.getLogger(__name__)

# Hardcoded super-admin allowlist. Anyone signing in with these emails gets
# is_super_admin=True on first materialization. Edit here to add more.
SUPER_ADMIN_EMAILS = {
    "hallucinogenplus@gmail.com",
    "lwastuargo@gmail.com",
}


def _extract_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    if authorization.startswith("Bearer "):
        return authorization[len("Bearer "):].strip()
    return authorization.strip()


async def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Verify Firebase ID token from Authorization: Bearer ..., return User.

    Auto-materializes the User row on first sign-in. Auto-grants super-admin
    if email is in SUPER_ADMIN_EMAILS. Also auto-claims any pending
    StoreMembership invites that match this email.
    """
    token = _extract_token(authorization)
    if not token:
        raise HTTPException(401, "Missing Authorization Bearer token")

    try:
        claims = verify_id_token(token)
    except ValueError as e:
        raise HTTPException(401, f"Invalid Firebase token: {e}")
    except RuntimeError as e:
        # Firebase not configured (no FIREBASE_SERVICE_ACCOUNT_JSON env)
        raise HTTPException(503, str(e))

    firebase_uid = claims.get("uid") or claims.get("sub") or ""
    email = (claims.get("email") or "").lower()
    if not email:
        raise HTTPException(401, "Firebase token has no email claim")
    display_name = claims.get("name") or claims.get("display_name")
    photo_url = claims.get("picture") or None
    is_super = email in SUPER_ADMIN_EMAILS

    try:
        # Find or create user. Prefer firebase_uid match; fall back to email
        user = (
            await db.execute(select(User).where(User.firebase_uid == firebase_uid))
        ).scalar_one_or_none()
        if user is None:
            user = (
                await db.execute(select(User).where(User.email == email))
            ).scalar_one_or_none()

        if user is None:
            user = User(
                firebase_uid=firebase_uid,
                email=email,
                display_name=display_name,
                photo_url=photo_url,
                is_super_admin=is_super,
            )
            db.add(user)
            await db.flush()
        else:
            if not user.firebase_uid and firebase_uid:
                user.firebase_uid = firebase_uid
            if display_name and not user.display_name:
                user.display_name = display_name
            if photo_url and not user.photo_url:
                user.photo_url = photo_url
            if is_super and not user.is_super_admin:
                user.is_super_admin = True

        # Cache attributes BEFORE commit (in case refresh fails)
        user_id_cached = user.id
        is_super_cached = user.is_super_admin

        # Claim any pending invites that match this email
        pending = (
            await db.execute(
                select(StoreMembership)
                .where(StoreMembership.invited_email == email)
                .where(StoreMembership.user_id.is_(None))
            )
        ).scalars().all()
        for inv in pending:
            inv.user_id = user_id_cached
            inv.accepted_at = datetime.now(timezone.utc)

        await db.commit()

        # Re-fetch the user fresh from DB to avoid touching expired/detached state
        user = (
            await db.execute(select(User).where(User.id == user_id_cached))
        ).scalar_one()
        return user
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.exception("get_current_user materialization failed for %s", email)
        raise HTTPException(500, f"auth materialization failed: {type(e).__name__}: {e}\n{traceback.format_exc()[-1500:]}")


async def can_access_store(
    db: AsyncSession,
    user: User,
    store_id: uuid.UUID,
    min_role: StoreRole = StoreRole.STAFF,
) -> bool:
    """Return True iff user has at least `min_role` access to store_id."""
    if user.is_super_admin:
        return True
    row = (
        await db.execute(
            select(StoreMembership)
            .where(StoreMembership.user_id == user.id)
            .where(StoreMembership.store_id == store_id)
        )
    ).scalar_one_or_none()
    if row is None:
        return False
    if min_role == StoreRole.STAFF:
        return True  # any role >= staff
    return row.role == min_role  # OWNER requires exact owner


async def require_store_access(
    store_id: str = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Dependency: 403 if user can't access this store."""
    try:
        sid = uuid.UUID(store_id)
    except (ValueError, TypeError):
        raise HTTPException(400, "store_id must be a UUID")
    if not await can_access_store(db, user, sid):
        raise HTTPException(403, "no access to this store")
    return user


async def require_store_owner(
    store_id: str = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Dependency: 403 unless user is super admin OR store owner."""
    try:
        sid = uuid.UUID(store_id)
    except (ValueError, TypeError):
        raise HTTPException(400, "store_id must be a UUID")
    if not await can_access_store(db, user, sid, min_role=StoreRole.OWNER):
        raise HTTPException(403, "store owner only")
    return user
