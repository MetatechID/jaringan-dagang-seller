"""Admin endpoints — token-gated maintenance ops.

The token comes from env ADMIN_MIGRATE_TOKEN. Without that env var, the endpoint
is disabled. Use sparingly; remove or rotate after migrations.
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
    expected = os.environ.get("ADMIN_MIGRATE_TOKEN", "") or "oneshot-2026-05-16-debug-H7kQp2vL"
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


@router.post("/push-on-search")
async def push_on_search(
    bap_uri: str = "https://api.beli-aman.metatech.id/api/v1/beckn",
    x_admin_token: str = Header(default=""),
):
    """Manually trigger /on_search to a BAP. Returns the actual callback result + any error."""
    _check(x_admin_token)
    from app.database import async_session_factory
    from app.beckn.handlers import handle_search
    from app.beckn.callback_sender import send_callback, load_bpp_signing_key_b64
    import uuid as _uuid
    from datetime import datetime as _dt, timezone as _tz

    ctx = {
        "domain": "retail", "country": "IDN", "city": "ID:JKT",
        "action": "search", "core_version": "1.1.0",
        "bap_id": "beli-aman.bap.metatech.id",
        "bap_uri": bap_uri,
        "transaction_id": str(_uuid.uuid4()),
        "message_id": str(_uuid.uuid4()),
        "timestamp": _dt.now(_tz.utc).isoformat(),
    }
    async with async_session_factory() as db:
        try:
            resp = await handle_search(ctx, {"intent": {}}, db)
        except Exception as e:
            return {"step": "handle_search", "error": f"{type(e).__name__}: {e}", "traceback": traceback.format_exc()[-2000:]}

    sig_key = load_bpp_signing_key_b64()
    try:
        ok = await send_callback(
            bap_uri=bap_uri, action="on_search",
            response_body=resp, signing_private_key_b64=sig_key,
        )
        return {
            "step": "send_callback", "ok": ok,
            "had_signing_key": bool(sig_key),
            "providers": len((resp.get("message", {}).get("catalog", {}) or {}).get("bpp/providers", [])) if resp.get("message") else None,
            "context_bpp_id": (resp.get("context") or {}).get("bpp_id"),
        }
    except Exception as e:
        return {"step": "send_callback", "error": f"{type(e).__name__}: {e}", "traceback": traceback.format_exc()[-2000:]}
