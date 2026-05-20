"""JSON-RPC dispatch tests for the MCP server."""

from __future__ import annotations

import pytest
from conftest import make_ctx, static_bap

from mcp_protocol import (
    MCP_PROTOCOL_VERSION,
    SERVER_NAME,
    SERVER_VERSION,
    handle_jsonrpc,
)


@pytest.fixture
def ctx(state_store):
    return make_ctx(static_bap({}), state_store)


@pytest.mark.asyncio
async def test_initialize_returns_expected_shape(ctx):
    resp = await handle_jsonrpc(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}, ctx,
    )
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 1
    result = resp["result"]
    assert result["protocolVersion"] == MCP_PROTOCOL_VERSION
    assert result["serverInfo"]["name"] == SERVER_NAME
    assert result["serverInfo"]["version"] == SERVER_VERSION
    assert "tools" in result["capabilities"]


@pytest.mark.asyncio
async def test_tools_list_returns_six_tools(ctx):
    resp = await handle_jsonrpc(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}, ctx,
    )
    tools = resp["result"]["tools"]
    names = {t["name"] for t in tools}
    assert names == {
        "search_products",
        "get_product",
        "cart_add",
        "cart_view",
        "start_checkout",
        "payment_status",
    }
    # Every tool must have a non-empty description + an inputSchema with type=object.
    for t in tools:
        assert t["description"]
        assert t["inputSchema"]["type"] == "object"
        assert "conversation_id" in t["inputSchema"]["properties"]


@pytest.mark.asyncio
async def test_unknown_method_returns_method_not_found(ctx):
    resp = await handle_jsonrpc(
        {"jsonrpc": "2.0", "id": 3, "method": "nonsense", "params": {}}, ctx,
    )
    assert resp["error"]["code"] == -32601
    assert "nonsense" in resp["error"]["message"]


@pytest.mark.asyncio
async def test_invalid_jsonrpc_version_rejected(ctx):
    resp = await handle_jsonrpc(
        {"jsonrpc": "1.0", "id": 4, "method": "initialize", "params": {}}, ctx,
    )
    assert resp["error"]["code"] == -32600


@pytest.mark.asyncio
async def test_tools_call_unknown_tool_returns_iserror(ctx):
    """Per MCP spec, unknown tool name surfaces as tool result with isError."""
    resp = await handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "nope", "arguments": {}},
        },
        ctx,
    )
    # NOT a JSON-RPC error — the tool envelope itself carries isError.
    assert "error" not in resp
    assert resp["result"]["isError"] is True
    assert "Unknown tool" in resp["result"]["content"][0]["text"]


@pytest.mark.asyncio
async def test_tools_call_missing_name_is_invalid_params(ctx):
    resp = await handle_jsonrpc(
        {
            "jsonrpc": "2.0", "id": 6, "method": "tools/call",
            "params": {"arguments": {}},
        },
        ctx,
    )
    assert resp["error"]["code"] == -32602


@pytest.mark.asyncio
async def test_initialized_notification_accepted(ctx):
    """MCP clients often send `notifications/initialized` after `initialize`."""
    resp = await handle_jsonrpc(
        {
            "jsonrpc": "2.0", "id": 7,
            "method": "notifications/initialized", "params": {},
        },
        ctx,
    )
    assert "error" not in resp
    assert resp["result"] == {}
