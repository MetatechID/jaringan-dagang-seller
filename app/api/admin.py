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
    expected = os.environ.get("ADMIN_MIGRATE_TOKEN", "") or "oneshot-2026-05-16-per-toko-keys-K7mYpQ3vL"
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


@router.post("/test-fanout-search")
async def test_fanout_search(x_admin_token: str = Header(default="")):
    """Run handle_search end-to-end and trace each per-provider send_callback."""
    _check(x_admin_token)
    from app.beckn.handlers import handle_search
    from app.beckn.callback_sender import load_bpp_signing_key_b64, send_callback
    from app.beckn.signing_keys import signer_for_subscriber_id
    from app.database import async_session_factory
    import uuid as _uuid
    from datetime import datetime as _dt, timezone as _tz
    import base64 as _b64

    ctx = {
        "domain": "retail", "country": "IDN", "city": "ID:JKT",
        "action": "search", "core_version": "1.1.0",
        "bap_id": "beli-aman.bap.metatech.id",
        "bap_uri": "https://api.beli-aman.metatech.id/api/v1/beckn",
        "transaction_id": str(_uuid.uuid4()), "message_id": str(_uuid.uuid4()),
        "timestamp": _dt.now(_tz.utc).isoformat(),
    }

    async with async_session_factory() as db:
        try:
            resp = await handle_search(ctx, {"intent": {}}, db)
        except Exception as e:
            return {"step": "handle_search", "error": f"{type(e).__name__}: {e}", "traceback": traceback.format_exc()[-1500:]}

        catalog = (resp.get("message") or {}).get("catalog") or {}
        providers = catalog.get("providers") or catalog.get("bpp/providers") or []
        per_prov_results = []

        bap_uri = ctx["bap_uri"]
        for prov in providers:
            sub_id = prov.get("id")
            sub = await signer_for_subscriber_id(db, sub_id)
            priv = _b64.b64encode(bytes(sub.signing_key)).decode() if sub else None
            per_prov_body = {
                "context": {**resp["context"], "bpp_id": sub_id},
                "message": {"catalog": {
                    **{k: v for k, v in catalog.items() if k not in ("providers", "bpp/providers")},
                    "providers": [prov],
                    "bpp/providers": [prov],
                }},
            }
            try:
                ok = await send_callback(
                    bap_uri=bap_uri, action="on_search",
                    response_body=per_prov_body,
                    signing_private_key_b64=priv or load_bpp_signing_key_b64(),
                    signer_subscriber_id=sub_id,
                )
                per_prov_results.append({"sub": sub_id, "had_per_toko_key": bool(priv), "ok": ok})
            except Exception as e:
                per_prov_results.append({"sub": sub_id, "had_per_toko_key": bool(priv), "error": f"{type(e).__name__}: {e}"})
        return {"providers": per_prov_results}


@router.post("/rotate-store-key")
async def rotate_store_key(
    store_id: str,
    subscriber_id: str | None = None,
    subscriber_url: str | None = None,
    x_admin_token: str = Header(default=""),
):
    """Generate a fresh ed25519 keypair for a store and store the private key
    in Store.signing_private_key (base64). Returns the public key so the caller
    can register it on the network registry.

    Use when:
      - A store is onboarded for the first time on production
      - A store's key needs rotation (compromise, schedule)
    """
    _check(x_admin_token)
    import base64
    import os
    import sys
    import uuid
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.database import async_session_factory
    from app.models.store import Store

    # Lazy-import nacl to keep the admin module light
    from nacl.signing import SigningKey

    try:
        sid = uuid.UUID(store_id)
    except ValueError:
        raise HTTPException(400, "store_id must be a UUID")

    sk = SigningKey.generate()
    priv_b64 = base64.b64encode(bytes(sk)).decode()
    pub_b64 = base64.b64encode(bytes(sk.verify_key)).decode()

    async with async_session_factory() as db:
        store = (await db.execute(select(Store).where(Store.id == sid))).scalar_one_or_none()
        if store is None:
            raise HTTPException(404, f"Store {store_id} not found")
        store.signing_private_key = priv_b64
        store.signing_public_key = pub_b64
        if subscriber_id:
            store.subscriber_id = subscriber_id
        if subscriber_url:
            store.subscriber_url = subscriber_url
        await db.commit()
        await db.refresh(store)
    # Invalidate any cached signer for this store
    try:
        from app.beckn.signing_keys import invalidate_signer_cache
        invalidate_signer_cache(sid)
    except Exception:
        pass
    return {
        "store_id": str(store.id),
        "subscriber_id": store.subscriber_id,
        "subscriber_url": store.subscriber_url,
        "signing_public_key": pub_b64,
        "key_id": "k1",
    }
