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


def load_bpp_signing_key_b64() -> str | None:
    """Load the BPP's signing private key as base64 from disk or env.

    Order:
      1. BPP_SIGNING_KEY_B64 env var (base64 directly)
      2. settings.BPP_SIGNING_KEY_PATH file (base64 text file)
    Returns None if neither is configured.
    """
    env_b64 = os.environ.get("BPP_SIGNING_KEY_B64")
    if env_b64:
        return env_b64.strip()
    key_path = getattr(settings, "BPP_SIGNING_KEY_PATH", None) or "dev/keys/seller.private.b64"
    if not os.path.isabs(key_path):
        # resolve relative to seller repo root
        key_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", key_path))
    try:
        with open(key_path) as f:
            return f.read().strip()
    except FileNotFoundError:
        logger.warning("BPP signing key not found at %s — callbacks will be unsigned", key_path)
        return None
    except Exception:
        logger.exception("failed to load BPP signing key")
        return None


def _get_signer(
    signing_private_key_b64: str | None,
    subscriber_id: str | None = None,
    unique_key_id: str | None = None,
) -> BecknSigner | None:
    """Build a BecknSigner from a base64-encoded private key, or None.

    `subscriber_id` defaults to the process-wide BPP id (settings); pass the
    per-toko subscriber id when signing on behalf of a specific store.
    """
    if not signing_private_key_b64:
        return None
    try:
        key_bytes = base64.b64decode(signing_private_key_b64)
        signing_key = SigningKey(key_bytes)
        return BecknSigner(
            signing_key=signing_key,
            subscriber_id=subscriber_id or settings.BPP_SUBSCRIBER_ID,
            unique_key_id=unique_key_id or settings.BPP_UNIQUE_KEY_ID,
        )
    except Exception:
        logger.exception("Failed to initialise BecknSigner")
        return None


async def send_callback(
    bap_uri: str,
    action: str,
    response_body: dict[str, Any],
    signing_private_key_b64: str | None = None,
    signer_subscriber_id: str | None = None,
    signer_key_id: str | None = None,
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

    # If a per-toko subscriber id wasn't explicitly given, try to derive it
    # from the response body's context.bpp_id so callbacks signed for a
    # specific store carry the right keyId.
    if not signer_subscriber_id:
        signer_subscriber_id = (response_body.get("context") or {}).get("bpp_id")
    signer = _get_signer(signing_private_key_b64, signer_subscriber_id, signer_key_id)
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
