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

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory, get_db

# Make the beckn-protocol package importable
_proto_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "packages", "beckn-protocol")
)
if _proto_path not in sys.path:
    sys.path.insert(0, _proto_path)

from python import AckMessage, AckResponse, AckStatus, BecknRequest

from app.beckn import handlers
from app.beckn.callback_sender import send_callback
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

            # Send callback to BAP
            bap_uri = context_dict.get("bap_uri", "")
            callback_action = f"on_{action}"
            if bap_uri:
                await send_callback(
                    bap_uri=bap_uri,
                    action=callback_action,
                    response_body=response_body,
                )

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
        background_tasks: BackgroundTasks,
    ):
        try:
            body = await request.json()
            beckn_req = BecknRequest(**body)
        except Exception as exc:
            logger.warning("Invalid Beckn request for %s: %s", action, exc)
            return _nack(f"Invalid request: {exc}")

        context_dict = beckn_req.context.model_dump(mode="json")
        message_dict = beckn_req.message

        background_tasks.add_task(
            _process_and_callback,
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
}

for _action, _handler in _ACTION_HANDLERS.items():
    _ep = _make_beckn_endpoint(_action, _handler)
    router.add_api_route(
        f"/{_action}",
        _ep,
        methods=["POST"],
        summary=f"Beckn {_action}",
    )
