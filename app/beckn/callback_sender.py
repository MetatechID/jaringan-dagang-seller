"""Send on_* callback responses to the BAP asynchronously.

Signs the request body with Ed25519 when signing keys are configured.
"""

from __future__ import annotations

import base64
import logging
import sys
import os
from typing import Any

import httpx

from app.config import settings

# Make the beckn-protocol package importable
_proto_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "packages", "beckn-protocol")
)
if _proto_path not in sys.path:
    sys.path.insert(0, _proto_path)

from python import BecknResponse, BecknSigner
from nacl.signing import SigningKey

logger = logging.getLogger(__name__)


def _get_signer(
    signing_private_key_b64: str | None,
) -> BecknSigner | None:
    """Build a BecknSigner from a base64-encoded private key, or None."""
    if not signing_private_key_b64:
        return None
    try:
        key_bytes = base64.b64decode(signing_private_key_b64)
        signing_key = SigningKey(key_bytes)
        return BecknSigner(
            signing_key=signing_key,
            subscriber_id=settings.BPP_SUBSCRIBER_ID,
            unique_key_id=settings.BPP_UNIQUE_KEY_ID,
        )
    except Exception:
        logger.exception("Failed to initialise BecknSigner")
        return None


async def send_callback(
    bap_uri: str,
    action: str,
    response_body: dict[str, Any],
    signing_private_key_b64: str | None = None,
) -> bool:
    """POST an on_* callback to the BAP.

    Args:
        bap_uri: The BAP's subscriber URL (context.bap_uri).
        action: The callback action name, e.g. "on_search".
        response_body: The full BecknResponse dict.
        signing_private_key_b64: Optional base64-encoded Ed25519 private key.

    Returns:
        True if the callback was sent successfully.
    """
    url = f"{bap_uri.rstrip('/')}/{action}"
    body_bytes = BecknResponse(**response_body).model_dump_json(
        exclude_none=True
    ).encode()

    headers: dict[str, str] = {"Content-Type": "application/json"}

    signer = _get_signer(signing_private_key_b64)
    if signer:
        auth_header = signer.sign(body_bytes)
        headers["Authorization"] = auth_header

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                content=body_bytes,
                headers=headers,
                timeout=30.0,
            )
            logger.info(
                "Callback %s -> %s  status=%s", action, url, resp.status_code
            )
            return 200 <= resp.status_code < 300
    except Exception:
        logger.exception("Failed to send callback %s to %s", action, url)
        return False
