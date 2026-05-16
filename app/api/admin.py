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
    expected = os.environ.get("ADMIN_MIGRATE_TOKEN", "")
    if not expected:
        raise HTTPException(503, "Admin disabled (set ADMIN_MIGRATE_TOKEN env)")
    if x_admin_token != expected:
        raise HTTPException(401, "Bad X-Admin-Token")
    try:
        async with engine.begin() as conn:
            def _create(sync_conn):
                Base.metadata.create_all(sync_conn, checkfirst=True)
            await conn.run_sync(_create)
        async with engine.begin() as conn:
            def _list(sync_conn):
                from sqlalchemy import inspect as sa_inspect
                return sa_inspect(sync_conn).get_table_names()
            tables = await conn.run_sync(_list)
        return {"ok": True, "tables_now": tables}
    except Exception as e:
        import traceback
        raise HTTPException(500, detail=f"{type(e).__name__}: {e}\n{traceback.format_exc()[-2000:]}")


@router.get("/db-tables")
async def list_tables(x_admin_token: str = Header(default="")):
    expected = os.environ.get("ADMIN_MIGRATE_TOKEN", "")
    if not expected:
        raise HTTPException(503, "Admin disabled (set ADMIN_MIGRATE_TOKEN env)")
    if x_admin_token != expected:
        raise HTTPException(401, "Bad X-Admin-Token")
    async with engine.begin() as conn:
        def _inspect(sync_conn):
            from sqlalchemy import inspect as sa_inspect
            insp = sa_inspect(sync_conn)
            return insp.get_table_names()
        names = await conn.run_sync(_inspect)
    return {"tables": names}
