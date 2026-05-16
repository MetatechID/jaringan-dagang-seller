"""Admin endpoints — token-gated maintenance ops.

The token comes from env ADMIN_MIGRATE_TOKEN. Without that env var, the
endpoints are disabled. Use sparingly; rotate the token after migrations.

Exposed:
    POST /api/admin/migrate    Create any missing DB tables (Base.metadata.create_all).
    GET  /api/admin/db-tables  List current DB tables.
"""

from __future__ import annotations

import os
import traceback

from fastapi import APIRouter, Header, HTTPException

from app.database import engine
from app.models.base import Base

# Import every model module so Base.metadata knows about all tables.
import app.models  # noqa: F401

router = APIRouter(prefix="/admin", tags=["admin"])


def _check(token: str) -> None:
    expected = os.environ.get("ADMIN_MIGRATE_TOKEN", "")
    if not expected:
        raise HTTPException(503, "Admin disabled (set ADMIN_MIGRATE_TOKEN env)")
    if token != expected:
        raise HTTPException(401, "Bad X-Admin-Token")


@router.post("/migrate")
async def migrate(x_admin_token: str = Header(default="")):
    _check(x_admin_token)
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
        raise HTTPException(500, detail=f"{type(e).__name__}: {e}\n{traceback.format_exc()[-2000:]}")


@router.get("/db-tables")
async def list_tables(x_admin_token: str = Header(default="")):
    _check(x_admin_token)
    async with engine.begin() as conn:
        def _inspect(sync_conn):
            from sqlalchemy import inspect as sa_inspect
            insp = sa_inspect(sync_conn)
            return insp.get_table_names()
        names = await conn.run_sync(_inspect)
    return {"tables": names}
