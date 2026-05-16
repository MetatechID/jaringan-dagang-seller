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


@router.get("/search-debug")
async def search_debug(x_admin_token: str = Header(default="")):
    """Diagnostic: count what handle_search would find."""
    _check(x_admin_token)
    from app.database import async_session_factory
    from app.services import catalog_service
    from app.models.product import Product, ProductStatus
    from sqlalchemy import select, func
    async with async_session_factory() as db:
        total = (await db.execute(select(func.count(Product.id)))).scalar()
        active = (await db.execute(
            select(func.count(Product.id)).where(Product.status == ProductStatus.ACTIVE)
        )).scalar()
        # try the actual search
        try:
            products = await catalog_service.search_products_all_stores(db)
            search_count = len(products)
            store_map = {}
            for p in products:
                sid = p.store_id
                store_map.setdefault(sid, [p.store.name if p.store else "?", 0])
                store_map[sid][1] += 1
            stores = [{"store_id": str(k), "name": v[0], "products": v[1]} for k, v in store_map.items()]
        except Exception as e:
            search_count = -1
            stores = [{"error": f"{type(e).__name__}: {e}"}]
    return {
        "total_products": total,
        "active_products": active,
        "search_returned": search_count,
        "stores": stores,
    }


@router.get("/build-catalog-debug")
async def build_catalog_debug(x_admin_token: str = Header(default="")):
    """Trace BecknCatalogBuilder.build_catalog step by step."""
    _check(x_admin_token)
    from app.database import async_session_factory
    from app.services import catalog_service
    from app.beckn.catalog_builder import BecknCatalogBuilder
    import uuid
    async with async_session_factory() as db:
        products = await catalog_service.search_products_all_stores(db)
        # Group by store
        store_map = {}
        for p in products:
            sid = p.store_id
            if sid not in store_map:
                store_map[sid] = (p.store, [])
            store_map[sid][1].append(p)
        out = []
        for store, prods in store_map.values():
            try:
                provider = BecknCatalogBuilder.build_provider(store, prods)
                out.append({"store": store.name, "provider_items": len(provider.items or []), "provider_id": provider.id})
            except Exception as e:
                out.append({"store": store.name, "error": f"{type(e).__name__}: {e}", "traceback": traceback.format_exc()[-1500:]})
        try:
            catalog = BecknCatalogBuilder.build_catalog([(s, p) for s, p in store_map.values()])
            providers_count = len(catalog.providers or [])
        except Exception as e:
            providers_count = -1
            out.append({"build_catalog_error": f"{type(e).__name__}: {e}"})
    return {"per_store": out, "catalog_providers": providers_count}


@router.post("/test-confirm")
async def test_confirm(sku_id: str, x_admin_token: str = Header(default="")):
    """Run handle_confirm with a synthetic Beckn /confirm envelope and report what happens."""
    _check(x_admin_token)
    from app.database import async_session_factory
    from app.beckn.handlers import handle_confirm
    import uuid as _uuid
    from datetime import datetime as _dt, timezone as _tz

    ctx = {
        "domain": "retail", "country": "IDN", "city": "ID:JKT",
        "action": "confirm", "core_version": "1.1.0",
        "bap_id": "beli-aman.bap.metatech.id",
        "bap_uri": "https://api.beli-aman.metatech.id/api/v1/beckn",
        "bpp_id": "bpp.jaringan-dagang.local",
        "transaction_id": str(_uuid.uuid4()),
        "message_id": str(_uuid.uuid4()),
        "timestamp": _dt.now(_tz.utc).isoformat(),
    }
    message = {
        "order": {
            "id": f"ADMIN-TEST-{_uuid.uuid4().hex[:8].upper()}",
            "items": [{"id": sku_id, "qty": 1}],
            "billing": {"name": "Admin Test", "email": "admin@test.local"},
            "fulfillments": [],
            "quote": {"price": {"value": "100000", "currency": "IDR"}},
            "payments": [{"type": "PRE-FULFILLMENT", "status": "PAID",
                          "params": {"amount": "100000", "currency": "IDR"}}],
        }
    }
    async with async_session_factory() as db:
        try:
            resp = await handle_confirm(ctx, message, db)
            await db.commit()
            return {"ok": True, "response": resp}
        except Exception as e:
            await db.rollback()
            return {"ok": False, "error": f"{type(e).__name__}: {e}", "traceback": traceback.format_exc()[-2500:]}


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
    # Try sending directly with httpx so we see the real HTTP outcome
    import json as _json
    import httpx as _httpx
    cat = (resp.get("message") or {}).get("catalog") or {}
    providers_via_canonical = len(cat.get("bpp/providers") or [])
    providers_via_alt = len(cat.get("providers") or [])
    try:
        ok = await send_callback(
            bap_uri=bap_uri, action="on_search",
            response_body=resp, signing_private_key_b64=sig_key,
        )
    except Exception as e:
        ok = f"exception: {type(e).__name__}: {e}"

    # Direct POST so we get HTTP status (send_callback swallows non-2xx)
    direct = {}
    try:
        body_bytes = _json.dumps(resp, separators=(",", ":")).encode()
        from python import BecknSigner
        from nacl.signing import SigningKey as _SK
        import base64 as _b64
        if sig_key:
            signer = BecknSigner(
                signing_key=_SK(_b64.b64decode(sig_key)),
                subscriber_id="bpp.jaringan-dagang.local", unique_key_id="k1",
            )
            auth = signer.sign(body_bytes)
        else:
            auth = None
        async with _httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                f"{bap_uri.rstrip('/')}/on_search",
                content=body_bytes,
                headers={"Content-Type": "application/json", "Authorization": auth} if auth else {"Content-Type": "application/json"},
            )
            direct = {"status": r.status_code, "body": r.text[:400]}
    except Exception as e:
        direct = {"error": f"{type(e).__name__}: {e}"}

    return {
        "step": "send_callback",
        "send_callback_ok": ok,
        "had_signing_key": bool(sig_key),
        "providers_canonical": providers_via_canonical,
        "providers_alt_key": providers_via_alt,
        "direct_http": direct,
    }
