# Vercel Functions

Night is an ASGI application, and Vercel's Python runtime accepts an `app` variable that exposes an ASGI or WSGI application. Night therefore runs on Vercel without a request/response translation layer.

A ready-to-copy example lives in [`deploy/vercel-night`](../../deploy/vercel-night).

## Minimal application

```python
from night import Night

app = Night()

@app.get("/")
def index():
    return {"hello": "vercel"}
```

Use a recognized Python entrypoint such as `app.py`, or declare one explicitly:

```toml
[tool.vercel]
entrypoint = "app.py"
```

Vercel's Python runtime reads Python version requirements and dependencies from `pyproject.toml`.

```toml
[project]
requires-python = ">=3.12"
dependencies = ["all-night>=0.1.1"]
```

## Deploy

Push the project to a Git provider connected to Vercel, or use the Vercel CLI:

```bash
vercel
```

For this repository's example, set `deploy/vercel-night` as the project root.

## Streaming

Vercel's Python runtime supports streaming responses. Night's `StreamingResponse` and SSE helpers remain ASGI responses, so they can use the normal Vercel Python streaming path.

## MCP on Vercel

The MCP transport is just a Night HTTP route, so it can run in the same Vercel Function:

```python
from night import Night
from night_mcp import enable_mcp

app = Night()
mcp = enable_mcp(app)

@mcp.tool()
def add(a: int, b: int):
    return {"value": a + b}
```

This is particularly useful with MCP 2026-07-28 because the protocol core is stateless: the endpoint does not require sticky sessions or an `Mcp-Session-Id`.

## Production notes

- Keep runtime dependencies and bundled files small; Python functions bundle reachable project files.
- Declare a Python version supported by Vercel's current Python runtime.
- Use environment variables for secrets rather than committing them.
- Treat local `vercel dev` as the closest development path when you need to test Vercel-specific routing or runtime behavior.
- Check Vercel's current runtime and Functions limits before relying on a specific bundle size, memory size, or maximum duration.

Night does not require `vercel.json` for the basic ASGI deployment shown here. Add it only when you need function-level Vercel settings such as duration or file exclusions.
