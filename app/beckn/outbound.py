"""Outbound Beckn message sender with DB logging.

Wraps callback_sender.send_callback so every attempt is recorded in
BecknOutboundLog for audit + retry visibility.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import uuid
from typing import Any

import httpx

from app.database import async_session_factory
from app.models.beckn_outbound_log import BecknOutboundLog

# Make the beckn-protocol package importable
_proto_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "packages", "beckn-protocol")
)
if _proto_path not in sys.path:
    sys.path.insert(0, _proto_path)

from python import BecknSigner  # noqa: E402
from nacl.signing import SigningKey  # noqa: E402

logger = logging.getLogger(__name__)

# Retry backoff: 0s, 1s, 4s, 16s
_RETRY_DELAYS = [0.0, 1.0, 4.0, 16.0]


async def send_beckn_callback(
    *,
    target_url: str,
    action: str,
    body: dict[str, Any],
    signer: BecknSigner | None = None,
    transaction_id: str | None = None,
    message_id: str | None = None,
) -> bool:
    """Send a signed Beckn callback. Logs every attempt to BecknOutboundLog.

    Args:
        target_url: Fully-qualified URL (e.g. http://bap/api/v1/beckn/on_search).
        action: Beckn action name (e.g. "on_search").
        body: JSON-serializable response body. context.message_id should already be set.
        signer: BecknSigner to use for signing. If None, posts unsigned (dev only).
        transaction_id: For logging only.
        message_id: For logging only. Falls back to body.context.message_id.

    Returns:
        True if any attempt got a 2xx response.
    """
    import json

    body_bytes = json.dumps(body, separators=(",", ":")).encode()
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if signer is not None:
        try:
            headers["Authorization"] = signer.sign(body_bytes)
        except Exception:
            logger.exception("failed to sign outbound %s", action)
            return False

    msg_id = message_id or (body.get("context") or {}).get("message_id") or str(uuid.uuid4())
    txn_id = transaction_id or (body.get("context") or {}).get("transaction_id")

    last_status: int | None = None
    for attempt, delay in enumerate(_RETRY_DELAYS, start=1):
        if delay:
            await asyncio.sleep(delay)
        log = BecknOutboundLog(
            message_id=msg_id,
            transaction_id=txn_id,
            action=action,
            target_url=target_url,
            attempt=attempt,
            request_body=body,
        )
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(target_url, content=body_bytes, headers=headers)
                log.response_status = resp.status_code
                try:
                    log.response_body = resp.json()
                except Exception:
                    log.response_body = {"text": resp.text[:500]}
        except Exception as e:
            log.error = repr(e)[:1000]
            async with async_session_factory() as db:
                db.add(log)
                await db.commit()
            continue

        async with async_session_factory() as db:
            db.add(log)
            await db.commit()

        last_status = resp.status_code
        if 200 <= resp.status_code < 300:
            return True
        if resp.status_code < 500:
            # 4xx — don't retry
            return False
    logger.warning("Beckn %s -> %s failed after retries (last=%s)", action, target_url, last_status)
    return False
