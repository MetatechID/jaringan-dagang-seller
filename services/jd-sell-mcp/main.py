"""FastAPI entrypoint for the jd-sell MCP server.

Single ``POST /mcp`` JSON-RPC endpoint + a ``GET /health`` for systemd /
the operator to confirm the process is up. The MCP server is loopback-only
by default (``MCP_BIND_HOST=127.0.0.1``); nullclaw runs on the same VM.

Lifespan wires:
  * one ``httpx.AsyncClient``-backed BAP client (env: ``BAP_BASE_URL``,
    ``BOT_API_TOKEN``, ``BAP_TIMEOUT_SEC``)
  * one ``ConversationStateStore`` (env: ``STATE_DB_PATH``)
  * one ``ToolContext`` shared by every request (its members are
    coroutine-safe, see comments in lib/conversation_state.py).

We avoid module-level singletons so that pytest fixtures can substitute
each piece via ``app.state``.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from lib.bap_client import build_default_client
from lib.conversation_state import ConversationStateStore
from mcp_protocol import handle_jsonrpc
from tools import ToolContext

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)
logger = logging.getLogger("jd-sell-mcp")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build singletons on startup; tear them down on shutdown."""
    ttl = int(os.environ.get("CATALOG_CACHE_TTL_SEC", "300"))
    bap = build_default_client()
    state = ConversationStateStore()
    ctx = ToolContext(bap=bap, state=state, catalog_cache_ttl_sec=ttl)
    app.state.ctx = ctx
    logger.info(
        "jd-sell-mcp ready · bap=%s · state_db=%s · cache_ttl_sec=%s",
        os.environ.get("BAP_BASE_URL"), state.db_path, ttl,
    )
    try:
        yield
    finally:
        await bap.aclose()


app = FastAPI(title="jd-sell-mcp", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "jd-sell-mcp",
        "version": "0.1.0",
        "bap_configured": bool(os.environ.get("BOT_API_TOKEN")),
    }


@app.post("/mcp")
async def mcp_endpoint(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception as exc:
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {exc}"},
            },
            status_code=400,
        )

    ctx: ToolContext = request.app.state.ctx
    resp = await handle_jsonrpc(payload, ctx)
    return JSONResponse(resp)
