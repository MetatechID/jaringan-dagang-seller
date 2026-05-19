"""Push the seller's full catalog as a Beckn /on_search to the registered BAPs.

Called automatically after product create/update/delete to keep the buyer's
mirror_* tables fresh in <1s.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.beckn.callback_sender import load_bpp_signing_key_b64, send_callback
from app.beckn.catalog_builder import BecknCatalogBuilder
from app.config import settings
from app.models.product import Product
from app.models.store import Store

# Make the beckn-protocol package importable
_proto_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "packages", "beckn-protocol")
)
if _proto_path not in sys.path:
    sys.path.insert(0, _proto_path)

from python.domain_resolver import resolve_ondc_domain  # noqa: E402

logger = logging.getLogger(__name__)

# Cached list of BAPs to notify. For v1: just Beli Aman.
# Later: read from a `bap_subscriptions` table maintained by BAP /subscribe events.
_KNOWN_BAPS: list[tuple[str, str]] = []


def _known_baps() -> list[tuple[str, str]]:
    """Return list of (bap_id, bap_uri) tuples to push to."""
    if _KNOWN_BAPS:
        return _KNOWN_BAPS
    bap_url = os.environ.get("BELI_AMAN_BAP_URL") or settings.BELI_AMAN_BAP_URL
    bap_id = os.environ.get("BELI_AMAN_BAP_ID") or settings.BELI_AMAN_BAP_ID
    return [(bap_id, bap_url)]


async def _build_full_catalog_message(
    db: AsyncSession,
) -> tuple[dict[str, Any], str | None]:
    """Build a full multi-store catalog payload for /on_search.

    Returns the message plus the single store's ``subscriber_id`` when the
    catalog contains exactly one store (today: Safiya only) so the envelope
    can carry that store's ONDC sub-domain; ``None`` when zero or many
    stores (no single sub-domain fits one multicast envelope).
    """
    res = await db.execute(
        select(Store)
        .where(Store.status == "active")
        .options(
            selectinload(Store.products).selectinload(Product.skus),
            selectinload(Store.products).selectinload(Product.images),
        )
    )
    stores = res.scalars().all()
    pairs: list[tuple[Store, list[Product]]] = [
        (s, list(s.products or [])) for s in stores if s.products
    ]
    if not pairs:
        return {"catalog": {"bpp/providers": []}}, None
    single_store_subscriber_id = (
        pairs[0][0].subscriber_id if len(pairs) == 1 else None
    )
    catalog = BecknCatalogBuilder.build_catalog(pairs)
    return (
        {"catalog": catalog.model_dump(exclude_none=True)},
        single_store_subscriber_id,
    )


def _build_context(
    bap_id: str, bap_uri: str, *, store_subscriber_id: str | None = None
) -> dict[str, Any]:
    # Per-store ONDC domain code (Safiya -> ONDC:RET11). When the catalog
    # spans multiple stores no single sub-domain fits one envelope, so we
    # leave store_subscriber_id=None and the resolver returns the
    # store-level ONDC:RET default. The Beckn transport base
    # (settings.BECKN_DOMAIN) is unchanged by this layer.
    return {
        "domain": resolve_ondc_domain(store_subscriber_id).domain_code,
        "country": settings.BECKN_COUNTRY_CODE,
        "city": settings.BECKN_CITY_CODE,
        "action": "on_search",
        "core_version": settings.BECKN_CORE_VERSION,
        "bap_id": bap_id,
        "bap_uri": bap_uri,
        "bpp_id": settings.BPP_SUBSCRIBER_ID,
        "bpp_uri": settings.BPP_SUBSCRIBER_URL,
        "transaction_id": str(uuid.uuid4()),
        "message_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def push_catalog(db: AsyncSession) -> None:
    """Push current catalog to all known BAPs. Best-effort; logs failures."""
    msg, store_subscriber_id = await _build_full_catalog_message(db)
    signing_key = load_bpp_signing_key_b64()
    targets = _known_baps()
    for bap_id, bap_uri in targets:
        ctx = _build_context(
            bap_id, bap_uri, store_subscriber_id=store_subscriber_id
        )
        body = {"context": ctx, "message": msg}
        try:
            ok = await send_callback(
                bap_uri=bap_uri,
                action="on_search",
                response_body=body,
                signing_private_key_b64=signing_key,
            )
            logger.info("catalog push -> %s : %s", bap_uri, "ok" if ok else "fail")
        except Exception:
            logger.exception("catalog push to %s failed", bap_uri)


def push_catalog_after_commit(db: AsyncSession) -> None:
    """Schedule a catalog push as a fire-and-forget background task.

    Safe to call inside an API handler that has just committed.
    """
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(_push_with_fresh_session())
    except RuntimeError:
        logger.warning("no running loop; skipping catalog push")


async def _push_with_fresh_session() -> None:
    from app.database import async_session_factory
    async with async_session_factory() as fresh:
        await push_catalog(fresh)
