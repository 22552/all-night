# Model Context Protocol (MCP)

Night can expose its existing RPC registry as a stateless **MCP 2026-07-28** server over HTTP.

The MCP integration lives in `night_mcp.py`, so the `night.py` ASGI core remains dependency-free and single-file friendly.

## Enable MCP

```python
from night import Night
from night_mcp import enable_mcp

app = Night()
mcp = enable_mcp(
    app,
    path="/mcp",
    name="my-night-service",
    instructions="Use the tools directly.",
)

@mcp.tool(description="Add two integers")
def add(a: int, b: int) -> dict:
    return {"value": a + b}
```

The same callable is also registered in Night's normal RPC registry.

Existing `@app.rpc(...)` methods are exposed automatically:

```python
@app.rpc("echo")
def echo(text: str):
    return {"echo": text}

mcp = enable_mcp(app)
```

## Implemented protocol surface

Night targets MCP protocol revision `2026-07-28` and currently implements the stateless HTTP core needed for tool servers:

- `server/discover`
- `tools/list`
- `tools/call`
- `MCP-Protocol-Version`
- `Mcp-Method`
- `Mcp-Name` validation for named calls
- response `resultType`
- server identity in `_meta.io.modelcontextprotocol/serverInfo`
- `ttlMs` / `cacheScope` on discovery and tool-list results

The 2026-07-28 MCP revision removes the protocol-level initialization/session requirement. Night therefore does not create or persist an `Mcp-Session-Id` for this transport.

## Tool schemas

Night derives a JSON Schema input object from the Python function signature and type annotations.

```python
@mcp.tool()
def search(query: str, limit: int = 10):
    ...
```

is advertised approximately as:

```json
{
  "name": "search",
  "inputSchema": {
    "type": "object",
    "properties": {
      "query": {"type": "string"},
      "limit": {"type": "integer"}
    },
    "required": ["query"]
  }
}
```

Primitive values, unions, lists, literals, mappings, and dataclasses receive lightweight schema generation without adding Pydantic or another validation dependency.

## Tool results

Dictionary results are returned as both text content and `structuredContent`.

```python
@mcp.tool()
def stats():
    return {"requests": 42}
```

Strings and scalar values are represented as text content. Sync and async tools are supported.

Exceptions raised by the tool body are returned as MCP tool results with `isError: true`. Protocol problems such as an unknown method, invalid arguments, or header/body mismatches use JSON-RPC error responses.

## Header validation

For MCP 2026-07-28 requests Night validates the HTTP routing headers against the JSON-RPC body. For example a tool call should resemble:

```http
POST /mcp
Content-Type: application/json
MCP-Protocol-Version: 2026-07-28
Mcp-Method: tools/call
Mcp-Name: search
```

If the mirrored HTTP headers disagree with the JSON-RPC body, Night returns MCP header-mismatch error code `-32020`.

## Caching

`enable_mcp()` defaults list/discovery results to:

```python
mcp = enable_mcp(app, ttl_ms=30_000, cache_scope="private")
```

Use `cache_scope="public"` only when the tool catalog and discovery response are safe to share across users.

## Deployment

MCP uses ordinary Night HTTP routes, so the same endpoint works under normal ASGI servers and Night's deployment targets, including Cloudflare Python Workers and Vercel Functions.

For Vercel see [Night on Vercel](../operations/vercel.md). For Cloudflare see [Cloudflare Python Workers](cloudflare-workers.md).

## Scope

This first implementation intentionally focuses on the modern stateless tool-server path. It does not yet implement MCP resources, prompts, Tasks, subscriptions, authorization helpers, legacy sessionful revisions, or Multi Round-Trip Requests.
