"""Beckn BPP protocol endpoints.

Implements all 10 Beckn actions as POST endpoints. Each:
  1. Accepts a BecknRequest body.
  2. Validates the request.
  3. Returns an immediate ACK response.
  4. Queues async processing via a FastAPI BackgroundTask.
  5. The background task calls the handler, then POSTs the callback to context.bap_uri.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

from fastapi import APIRouter, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory, get_db

# Make the beckn-protocol package importable
_proto_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "packages", "beckn-protocol")
)
if _proto_path not in sys.path:
    sys.path.insert(0, _proto_path)

from python import AckMessage, AckResponse, AckStatus, BecknRequest

from app.beckn import handlers
from app.beckn.callback_sender import send_callback
from app.beckn.middleware import check_idempotency, verify_inbound_signature
from app.models.beckn_transaction_log import BecknTransactionLog

logger = logging.getLogger(__name__)

router = APIRouter(tags=["beckn"])


# ------------------------------------------------------------------
# Helper: background task wrapper
# ------------------------------------------------------------------


async def _process_and_callback(
    action: str,
    handler,
    context_dict: dict[str, Any],
    message_dict: dict[str, Any],
    request_body: dict[str, Any],
) -> None:
    """Run the handler inside a fresh DB session, then send the callback."""
    async with async_session_factory() as db:
        try:
            # Execute the handler
            response_body = await handler(context_dict, message_dict, db)
            await db.commit()

            # Log the transaction
            log_entry = BecknTransactionLog(
                transaction_id=context_dict.get("transaction_id", ""),
                message_id=context_dict.get("message_id", ""),
                action=action,
                request_body=request_body,
                response_body=response_body,
                bap_id=context_dict.get("bap_id"),
            )
            db.add(log_entry)
            await db.commit()

            # Send callback to BAP. Two paths:
            # 1. /search fan-out: if the catalog has multiple providers, emit
            #    one /on_search per provider, each signed with that toko's key.
            #    Buyer's handler is idempotent + per-provider so this is safe.
            # 2. Everything else: single send, signed with per-store key if the
            #    response's context.bpp_id maps to a known store, otherwise the
            #    process-wide BPP key.
            bap_uri = context_dict.get("bap_uri", "")
            callback_action = f"on_{action}"
            if bap_uri:
                import base64 as _b64
                from app.beckn.callback_sender import load_bpp_signing_key_b64
                from app.beckn.signing_keys import signer_for_subscriber_id

                async def _sign_and_send(body: dict):
                    resp_bpp_id = (body.get("context") or {}).get("bpp_id")
                    per_store_priv_b64 = None
                    if resp_bpp_id and resp_bpp_id != settings.BPP_SUBSCRIBER_ID:
                        s = await signer_for_subscriber_id(db, resp_bpp_id)
                        if s is not None:
                            per_store_priv_b64 = _b64.b64encode(bytes(s.signing_key)).decode()
                    if per_store_priv_b64:
                        # Sign as the toko
                        await send_callback(
                            bap_uri=bap_uri, action=callback_action,
                            response_body=body,
                            signing_private_key_b64=per_store_priv_b64,
                            signer_subscriber_id=resp_bpp_id,
                        )
                    else:
                        # No toko key configured — sign as the process BPP and
                        # rewrite context.bpp_id so the buyer can verify our
                        # signature against the process key (avoids "claim toko
                        # identity with wrong private key" mismatch).
                        rebranded = {**body, "context": {**body.get("context", {}),
                                                         "bpp_id": settings.BPP_SUBSCRIBER_ID}}
                        await send_callback(
                            bap_uri=bap_uri, action=callback_action,
                            response_body=rebranded,
                            signing_private_key_b64=load_bpp_signing_key_b64(),
                            signer_subscriber_id=settings.BPP_SUBSCRIBER_ID,
                        )

                catalog = (response_body.get("message") or {}).get("catalog") or {}
                providers = catalog.get("providers") or catalog.get("bpp/providers") or []
                if action == "search" and len(providers) > 1:
                    base_ctx = response_body.get("context") or {}
                    for prov in providers:
                        provider_sub_id = prov.get("id")
                        if not provider_sub_id:
                            continue
                        per_prov_body = {
                            "context": {**base_ctx, "bpp_id": provider_sub_id},
                            "message": {"catalog": {
                                **{k: v for k, v in catalog.items() if k not in ("providers", "bpp/providers")},
                                "providers": [prov],
                                "bpp/providers": [prov],
                            }},
                        }
                        await _sign_and_send(per_prov_body)
                else:
                    await _sign_and_send(response_body)

        except Exception:
            logger.exception("Error processing Beckn %s action", action)
            await db.rollback()


def _ack() -> dict[str, Any]:
    """Build a synchronous ACK response."""
    return AckResponse(
        message=AckMessage(status=AckStatus.ACK),
    ).model_dump(exclude_none=True)


def _nack(error_message: str) -> dict[str, Any]:
    """Build a synchronous NACK response."""
    return AckResponse(
        message=AckMessage(status=AckStatus.NACK),
        error={
            "type": "CONTEXT-ERROR",
            "code": "10000",
            "message": error_message,
        },
    ).model_dump(exclude_none=True)


# ------------------------------------------------------------------
# Generic endpoint factory
# ------------------------------------------------------------------


def _make_beckn_endpoint(action: str, handler):
    """Create a POST endpoint for a given Beckn action."""

    async def endpoint(
        request: Request,
    ):
        # 1. Read raw body once for signature verification
        raw_body = await request.body()

        # 2. Verify Beckn signature (raises HTTPException on failure)
        await verify_inbound_signature(request, raw_body)

        # 3. Parse body
        try:
            body = await request.json()
            beckn_req = BecknRequest(**body)
        except Exception as exc:
            logger.warning("Invalid Beckn request for %s: %s", action, exc)
            return _nack(f"Invalid request: {exc}")

        context_dict = beckn_req.context.model_dump(mode="json")
        message_dict = beckn_req.message
        message_id = context_dict.get("message_id", "")

        # 4. Idempotency: if we've seen this message_id, return cached response
        async with async_session_factory() as dedupe_db:
            cached = await check_idempotency(dedupe_db, message_id)
            if cached is not None:
                return _ack()  # cached response was the original ACK; reissue

        # 5. Run processing inline (Vercel serverless — no background tasks)
        await _process_and_callback(
            action,
            handler,
            context_dict,
            message_dict,
            body,
        )

        return _ack()

    endpoint.__name__ = f"beckn_{action}"
    endpoint.__doc__ = f"Beckn {action} endpoint."
    return endpoint


# ------------------------------------------------------------------
# Register all 10 Beckn endpoints
# ------------------------------------------------------------------

_ACTION_HANDLERS = {
    "search": handlers.handle_search,
    "select": handlers.handle_select,
    "init": handlers.handle_init,
    "confirm": handlers.handle_confirm,
    "status": handlers.handle_status,
    "track": handlers.handle_track,
    "cancel": handlers.handle_cancel,
    "update": handlers.handle_update,
    "rating": handlers.handle_rating,
    "support": handlers.handle_support,
    # ONDC IGM (Task A5) — refund-request scope.
    "issue": handlers.handle_issue,
}

for _action, _handler in _ACTION_HANDLERS.items():
    _ep = _make_beckn_endpoint(_action, _handler)
    router.add_api_route(
        f"/{_action}",
        _ep,
        methods=["POST"],
        summary=f"Beckn {_action}",
    )
