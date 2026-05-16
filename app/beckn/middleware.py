"""Beckn signature verification + idempotency helpers.

Used inside the /beckn/* endpoint factory in app/beckn/endpoints.py.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Make the beckn-protocol package importable
_proto_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "packages", "beckn-protocol")
)
if _proto_path not in sys.path:
    sys.path.insert(0, _proto_path)

from python import RegistryClient, SubscriberNotFound, verify_request  # noqa: E402

from app.config import settings  # noqa: E402
from app.models.beckn_transaction_log import BecknTransactionLog  # noqa: E402

logger = logging.getLogger(__name__)

# Require signatures by default. Override with BECKN_REQUIRE_SIGNATURE=false for local dev.
REQUIRE_SIGNATURE = os.environ.get("BECKN_REQUIRE_SIGNATURE", "true").lower() != "false"

# Singleton registry client. Lazy init.
_registry: RegistryClient | None = None


def _get_registry() -> RegistryClient:
    global _registry
    if _registry is None:
        _registry = RegistryClient(
            registry_url=settings.REGISTRY_URL or "http://localhost:3030",
        )
    return _registry


_KEY_ID_RE = re.compile(r'keyId="([^"]+)"')


def _extract_subscriber_id(auth_header: str) -> str | None:
    """Parse the keyId from a Beckn Signature header.

    Format: keyId="<subscriber_id>|<unique_key_id>|ed25519"
    Returns the subscriber_id portion.
    """
    m = _KEY_ID_RE.search(auth_header)
    if not m:
        return None
    key_id = m.group(1)
    # key_id format: subscriber_id|unique_key_id|algorithm
    parts = key_id.split("|")
    if len(parts) >= 1:
        return parts[0]
    return None


async def verify_inbound_signature(request: Request, body: bytes) -> str | None:
    """Verify the request's Beckn signature.

    Returns the verified subscriber_id (the BAP_id) on success.

    Raises HTTPException(401) on:
      - missing Authorization header (when REQUIRE_SIGNATURE=true)
      - malformed header
      - unknown subscriber
      - bad signature / expired

    When REQUIRE_SIGNATURE=false (dev), missing header logs a warning and returns None.
    """
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if not auth:
        if REQUIRE_SIGNATURE:
            raise HTTPException(401, "Missing Authorization header")
        logger.warning("inbound Beckn request without Authorization (dev mode)")
        return None

    subscriber_id = _extract_subscriber_id(auth)
    if not subscriber_id:
        raise HTTPException(401, "Malformed Authorization header (no keyId)")

    try:
        sub = await _get_registry().lookup(subscriber_id)
    except SubscriberNotFound:
        raise HTTPException(401, f"Unknown subscriber: {subscriber_id}")
    except Exception as e:
        # Registry down or transient — fail closed in strict mode, open in dev
        if REQUIRE_SIGNATURE:
            logger.exception("Registry lookup failed for %s", subscriber_id)
            raise HTTPException(503, f"Registry lookup failed: {e}")
        logger.warning("Registry unreachable; skipping signature verify in dev mode: %s", e)
        return subscriber_id

    if not verify_request(body, auth, sub.signing_public_key_b64):
        raise HTTPException(401, f"Invalid Beckn signature from {subscriber_id}")

    return subscriber_id


async def check_idempotency(
    db: AsyncSession, message_id: str
) -> dict[str, Any] | None:
    """If we've already processed this message_id, return its prior response_body.

    Caller should short-circuit and return this directly without re-executing
    the handler.
    """
    if not message_id:
        return None
    existing = (
        await db.execute(
            select(BecknTransactionLog).where(
                BecknTransactionLog.message_id == message_id
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        return None
    logger.info(
        "Beckn idempotency hit on message_id=%s (action=%s) — returning cached response",
        message_id,
        existing.action,
    )
    return existing.response_body
