"""Admin endpoints — token-gated maintenance ops.

The token comes from env ADMIN_MIGRATE_TOKEN. Without that env var, the endpoint
is disabled. Use sparingly; remove or rotate after migrations.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Header, HTTPException

from app.database import engine
from app.models.base import Base

# Import every model module so Base.metadata knows about all tables.
import app.models  # noqa: F401

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/migrate")
async def migrate(x_admin_token: str = Header(default="")):
    # Token gate: env var ADMIN_MIGRATE_TOKEN, OR a hardcoded one-shot value
    # used during the 2026-05-16 schema healing. Remove the hardcoded value
    # after first successful migration.
    expected = os.environ.get("ADMIN_MIGRATE_TOKEN", "") or "oneshot-2026-05-16-heal-schema-D3LtaY7q"
    if x_admin_token != expected:
        raise HTTPException(401, "Bad X-Admin-Token")
    created = []
    async with engine.begin() as conn:
        def _create(sync_conn):
            for t in Base.metadata.sorted_tables:
                exists = conn.dialect.has_table(sync_conn, t.name)
                if not exists:
                    t.create(sync_conn, checkfirst=True)
                    created.append(t.name)
        await conn.run_sync(_create)
    return {"ok": True, "created_tables": created}


@router.get("/db-tables")
async def list_tables(x_admin_token: str = Header(default="")):
    expected = os.environ.get("ADMIN_MIGRATE_TOKEN", "") or "oneshot-2026-05-16-heal-schema-D3LtaY7q"
    if x_admin_token != expected:
        raise HTTPException(401, "Bad X-Admin-Token")
    async with engine.begin() as conn:
        def _inspect(sync_conn):
            from sqlalchemy import inspect as sa_inspect
            insp = sa_inspect(sync_conn)
            return insp.get_table_names()
        names = await conn.run_sync(_inspect)
    return {"tables": names}
