import json

from night import Night
from night_mcp import MCP_PROTOCOL_VERSION, enable_mcp


def _request(client, method, *, params=None, name=None, request_id=1):
    payload = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": {
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": MCP_PROTOCOL_VERSION,
                "io.modelcontextprotocol/clientCapabilities": {},
                "io.modelcontextprotocol/clientInfo": {"name": "test", "version": "1.0"},
            },
            **(params or {}),
        },
    }
    headers = {
        "content-type": "application/json",
        "mcp-protocol-version": MCP_PROTOCOL_VERSION,
        "mcp-method": method,
    }
    if name is not None:
        headers["mcp-name"] = name
    return client.post("/mcp", data=json.dumps(payload), headers=headers)


def test_mcp_discover_and_tools_list_from_rpc_registry():
    app = Night()

    @app.rpc("add")
    def add(a: int, b: int = 1):
        """Add two integers."""
        return {"value": a + b}

    enable_mcp(app, name="night-test", version="9.9.9", instructions="Use the tools directly.")

    with app.test_client() as client:
        discover = _request(client, "server/discover").get_json()
        assert discover["result"]["supportedVersions"] == [MCP_PROTOCOL_VERSION]
        assert discover["result"]["capabilities"] == {"tools": {"listChanged": False}}
        assert discover["result"]["instructions"] == "Use the tools directly."
        assert discover["result"]["resultType"] == "complete"
        assert discover["result"]["_meta"]["io.modelcontextprotocol/serverInfo"]["name"] == "night-test"

        listed = _request(client, "tools/list").get_json()
        tool = next(item for item in listed["result"]["tools"] if item["name"] == "add")
        assert tool["description"] == "Add two integers."
        assert tool["inputSchema"]["properties"]["a"] == {"type": "integer"}
        assert tool["inputSchema"]["properties"]["b"] == {"type": "integer"}
        assert tool["inputSchema"]["required"] == ["a"]
        assert listed["result"]["ttlMs"] == 30_000
        assert listed["result"]["cacheScope"] == "private"


def test_mcp_tool_decorator_sync_and_async_calls():
    app = Night()
    mcp = enable_mcp(app)

    @mcp.tool(description="Echo text")
    def echo(text: str):
        return {"echo": text}

    @mcp.tool("double")
    async def double(value: int):
        return value * 2

    with app.test_client() as client:
        echo_result = _request(
            client,
            "tools/call",
            name="echo",
            params={"name": "echo", "arguments": {"text": "night"}},
        ).get_json()["result"]
        assert echo_result["isError"] is False
        assert echo_result["structuredContent"] == {"echo": "night"}

        double_result = _request(
            client,
            "tools/call",
            name="double",
            params={"name": "double", "arguments": {"value": 21}},
        ).get_json()["result"]
        assert double_result["content"][0]["text"] == "42"


def test_mcp_header_mismatch_and_protocol_errors():
    app = Night()

    @app.rpc("echo")
    def echo(text: str):
        return text

    enable_mcp(app)

    with app.test_client() as client:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "_meta": {
                    "io.modelcontextprotocol/protocolVersion": MCP_PROTOCOL_VERSION,
                    "io.modelcontextprotocol/clientCapabilities": {},
                },
                "name": "echo",
                "arguments": {"text": "x"},
            },
        }
        response = client.post(
            "/mcp",
            data=json.dumps(payload),
            headers={
                "content-type": "application/json",
                "mcp-protocol-version": MCP_PROTOCOL_VERSION,
                "mcp-method": "tools/list",
                "mcp-name": "echo",
            },
        )
        assert response.status_code == 400
        assert response.get_json()["error"]["code"] == -32020

        unknown = _request(
            client,
            "tools/call",
            name="missing",
            params={"name": "missing", "arguments": {}},
        ).get_json()
        assert unknown["error"]["code"] == -32601

        invalid = _request(
            client,
            "tools/call",
            name="echo",
            params={"name": "echo", "arguments": {}},
        ).get_json()
        assert invalid["error"]["code"] == -32602


def test_mcp_tool_execution_error_is_tool_result():
    app = Night()
    mcp = enable_mcp(app)

    @mcp.tool()
    def fail():
        raise RuntimeError("boom")

    with app.test_client() as client:
        result = _request(
            client,
            "tools/call",
            name="fail",
            params={"name": "fail", "arguments": {}},
        ).get_json()["result"]
        assert result["isError"] is True
        assert result["content"][0]["text"] == "boom"
