"""Per-toko signing key resolution.

Returns a BecknSigner for a given store. Looks up the key in this order:
  1. Store.signing_private_key column (base64) — preferred, allows DB-managed keys
  2. dev/keys/<slug>.private.b64 file — dev fallback

The slug is derived from Store.name (lowercased, no spaces) for now;
when Store.bpp_id (or similar) is added this should switch to that.
"""

from __future__ import annotations

import base64
import logging
import os
import re
import sys
import uuid
from pathlib import Path

from nacl.signing import SigningKey
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Import BecknSigner
_proto_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "packages", "beckn-protocol")
)
if _proto_path not in sys.path:
    sys.path.insert(0, _proto_path)

from python import BecknSigner  # noqa: E402

from app.models.store import Store  # noqa: E402

logger = logging.getLogger(__name__)

# Map from store name (case-insensitive contains match) to canonical BPP subscriber_id.
# Used as the fallback when Store.subscriber_id isn't yet populated with the
# fully-qualified network id.
_NAME_TO_BPP_ID: dict[str, str] = {
    "safiya": "safiyafood.bpp.metatech.id",
    "antarestar": "antarestar.bpp.metatech.id",
    "gendes": "gendes.bpp.metatech.id",
    "yourbrand": "yourbrand.bpp.metatech.id",
}


def _slug_from_bpp_id(bpp_id: str) -> str:
    # safiyafood.bpp.metatech.id -> safiyafood
    return bpp_id.split(".", 1)[0]


def _slug_from_store(store: Store) -> str:
    if store.subscriber_id and "." in store.subscriber_id:
        return _slug_from_bpp_id(store.subscriber_id)
    n = (store.name or "").lower()
    for needle, bpp in _NAME_TO_BPP_ID.items():
        if needle in n:
            return _slug_from_bpp_id(bpp)
    raise ValueError(f"cannot determine signing slug for store {store.id} ({store.name})")


def bpp_id_for_store(store: Store) -> str:
    """Return the canonical BPP subscriber_id for this store."""
    if store.subscriber_id and "." in store.subscriber_id:
        return store.subscriber_id
    n = (store.name or "").lower()
    for needle, bpp in _NAME_TO_BPP_ID.items():
        if needle in n:
            return bpp
    raise ValueError(f"cannot determine BPP id for store {store.id} ({store.name})")


def _load_signer_from_file(slug: str, subscriber_id: str) -> BecknSigner | None:
    repo_root = Path(__file__).parent.parent.parent
    path = repo_root / "dev" / "keys" / f"{slug}.private.b64"
    if not path.exists():
        logger.warning("no dev key file at %s", path)
        return None
    try:
        priv_b64 = path.read_text().strip()
        sk = SigningKey(base64.b64decode(priv_b64))
        return BecknSigner(
            signing_key=sk,
            subscriber_id=subscriber_id,
            unique_key_id="k1",
        )
    except Exception:
        logger.exception("failed to load signing key from %s", path)
        return None


def _load_signer_from_db(store: Store) -> BecknSigner | None:
    if not store.signing_private_key:
        return None
    try:
        sk = SigningKey(base64.b64decode(store.signing_private_key))
        return BecknSigner(
            signing_key=sk,
            subscriber_id=bpp_id_for_store(store),
            unique_key_id="k1",
        )
    except Exception:
        logger.exception("failed to load signing key from DB for store %s", store.id)
        return None


_signer_cache: dict[uuid.UUID, BecknSigner] = {}


async def signer_for_store(store: Store) -> BecknSigner | None:
    """Get a cached BecknSigner for this store."""
    cached = _signer_cache.get(store.id)
    if cached is not None:
        return cached
    signer = _load_signer_from_db(store) or _load_signer_from_file(
        _slug_from_store(store), bpp_id_for_store(store)
    )
    if signer is not None:
        _signer_cache[store.id] = signer
    return signer


async def signer_for_store_id(db: AsyncSession, store_id) -> BecknSigner | None:
    store = (await db.execute(select(Store).where(Store.id == store_id))).scalar_one_or_none()
    if store is None:
        return None
    return await signer_for_store(store)


async def signer_for_subscriber_id(db: AsyncSession, subscriber_id: str) -> BecknSigner | None:
    """Resolve a Beckn subscriber_id (e.g. 'safiyafood.jaringan-dagang.id') to a
    signer by looking up the matching Store row. Returns None if no store has
    that subscriber_id or no key is configured."""
    if not subscriber_id:
        return None
    store = (await db.execute(
        select(Store).where(Store.subscriber_id == subscriber_id)
    )).scalar_one_or_none()
    if store is None:
        return None
    return await signer_for_store(store)


def invalidate_signer_cache(store_id=None) -> None:
    """Drop cached signer(s). Call after rotate_store_key."""
    if store_id is None:
        _signer_cache.clear()
    else:
        _signer_cache.pop(store_id, None)
