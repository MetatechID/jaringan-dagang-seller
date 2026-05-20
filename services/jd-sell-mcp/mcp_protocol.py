"""Hand-rolled MCP JSON-RPC 2.0 dispatcher.

We do NOT pull in the official ``mcp`` Python SDK. Three reasons:

1. The MCP surface we expose is exactly three methods: ``initialize``,
   ``tools/list``, ``tools/call``. The SDK's added value (streaming,
   resources, prompts, sampling, transports) is precisely the surface
   nullclaw's HTTP-MCP client does NOT use. Adding the SDK would bring
   ~10x the LOC and a new dependency churn axis.

2. We get an audit surface of ~80 LOC that any reviewer can read in 5
   minutes, vs. opaque framework behaviour. Bot-facing tool servers are
   security-sensitive (they bridge an LLM to a payment-issuing BAP) — small
   wins.

3. The MCP wire format for these three methods is trivial. See the spec
   at https://spec.modelcontextprotocol.io/specification/2024-11-05/.
"""

from __future__ import annotations

import logging
from typing import Any

from tools import ToolContext, dispatch as dispatch_tool, tool_descriptors

logger = logging.getLogger(__name__)


MCP_PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "jd-sell-mcp"
SERVER_VERSION = "0.1.0"


# JSON-RPC standard error codes (subset we actually use).
JSONRPC_PARSE_ERROR = -32700
JSONRPC_INVALID_REQUEST = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602
JSONRPC_INTERNAL_ERROR = -32603


def _rpc_response(req_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _rpc_error(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": code, "message": message},
    }


def _initialize_result() -> dict[str, Any]:
    return {
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        # `tools` capability declared with empty object per spec.
        # We don't expose resources/prompts/sampling.
        "capabilities": {"tools": {}},
    }


async def handle_jsonrpc(
    payload: dict[str, Any],
    ctx: ToolContext,
) -> dict[str, Any]:
    """Top-level dispatch. Returns a JSON-RPC response dict."""

    if not isinstance(payload, dict):
        return _rpc_error(None, JSONRPC_INVALID_REQUEST, "Request must be a JSON object")

    req_id = payload.get("id")
    method = payload.get("method")
    if payload.get("jsonrpc") != "2.0":
        return _rpc_error(req_id, JSONRPC_INVALID_REQUEST, "Missing jsonrpc=2.0")
    if not isinstance(method, str) or not method:
        return _rpc_error(req_id, JSONRPC_INVALID_REQUEST, "Missing/invalid method")

    params = payload.get("params") or {}
    if not isinstance(params, dict):
        return _rpc_error(req_id, JSONRPC_INVALID_PARAMS, "params must be an object")

    if method == "initialize":
        return _rpc_response(req_id, _initialize_result())

    # MCP clients commonly send an `initialized` notification after the
    # handshake. Some send it as a request (with id). Either way we accept
    # without action.
    if method in ("initialized", "notifications/initialized"):
        return _rpc_response(req_id, {})

    if method == "tools/list":
        return _rpc_response(req_id, {"tools": tool_descriptors()})

    if method == "tools/call":
        return await _handle_tools_call(req_id, params, ctx)

    return _rpc_error(req_id, JSONRPC_METHOD_NOT_FOUND, f"Method not found: {method}")


async def _handle_tools_call(
    req_id: Any,
    params: dict[str, Any],
    ctx: ToolContext,
) -> dict[str, Any]:
    name = params.get("name")
    arguments = params.get("arguments") or {}
    if not isinstance(name, str) or not name:
        return _rpc_error(req_id, JSONRPC_INVALID_PARAMS, "tools/call requires `name`")
    if not isinstance(arguments, dict):
        return _rpc_error(req_id, JSONRPC_INVALID_PARAMS, "`arguments` must be object")

    fn = dispatch_tool(name)
    if fn is None:
        # Per MCP spec, unknown tool name surfaces as ``isError: true`` in
        # the tool result envelope, NOT as a JSON-RPC error. This lets the
        # LLM see the failure and recover (e.g. by listing tools).
        return _rpc_response(
            req_id,
            {
                "content": [
                    {"type": "text", "text": f"Unknown tool: {name}"},
                ],
                "isError": True,
            },
        )

    try:
        result = await fn(ctx, arguments)
    except Exception as exc:  # pragma: no cover — last-resort safety net
        logger.exception("Tool %s raised", name)
        return _rpc_response(
            req_id,
            {
                "content": [
                    {"type": "text", "text": f"Internal error in tool {name}: {exc}"},
                ],
                "isError": True,
            },
        )

    body: dict[str, Any] = {"content": result.content}
    if result.is_error:
        body["isError"] = True
    return _rpc_response(req_id, body)
