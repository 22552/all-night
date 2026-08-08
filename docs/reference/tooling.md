# Tooling, testing, RPC, MCP, and extensions

## CLI

Installing `all-night` exposes the `night` command.

### Run an application

```bash
night run app.py
night run app.py --host 0.0.0.0 --port 8080
```

`night run` loads the selected Python file with `runpy.run_path()`, looks for a top-level `app`, and serves it with Uvicorn. If the file does not define `app`, Night falls back to the example application bundled in `night.py`.

Because the current CLI imports Uvicorn only when `night run` is used, install it separately:

```bash
python -m pip install -U uvicorn
```

You can also run the application directly with Uvicorn, Hypercorn, or another ASGI server:

```bash
uvicorn app:app --reload
```

### Routes and shell in 0.1.4

The current 0.1.4 parser defines `routes` and `shell` without an application-file argument:

```bash
night routes
night shell
```

These commands currently operate on the module-level Night application rather than loading `app.py`. Older documentation incorrectly showed:

```text
night routes app.py
night shell app.py
```

Do not rely on those older forms. A future CLI revision can make `routes` and `shell` load an explicit application file in the same way as `night run`.

### CLI summary

| Command | Current behavior |
| --- | --- |
| `night run FILE` | Load `FILE`, find `app`, and serve it with Uvicorn |
| `night run FILE --host HOST --port PORT` | Same, with explicit bind address |
| `night routes` | Print routes from the module-level Night app |
| `night shell` | Open an interactive shell around the module-level Night app |

## Testing

```python
with app.test_client() as client:
    response = client.get("/health")
    assert response.status_code == 200
```

`TestClient` calls Night in-process, retains cookies between requests, and reuses an `asyncio.Runner` instead of creating a new event loop for every request.

Call `client.close()` when not using it as a context manager. A closed client can lazily create a new Runner on the next request.

`TestResponse` exposes:

- `status_code`
- `headers`
- `data`
- `text`
- `get_json()`

Cross-framework TestClient benchmarks are intentionally labeled as rough comparisons because each framework's client performs different bookkeeping. Use a real HTTP server benchmark before making production throughput claims.

## Middleware and hooks

Register application middleware with `app.use(middleware)`. A middleware receives `(req, call_next)` and returns a response.

Built-ins include `logger_middleware`, `cors_middleware`, and `csrf_middleware`.

Use `before_request`, `after_request`, and `errorhandler` for lifecycle customization. Night has fast paths for applications with no middleware or hooks.

## Extensions

`app.register_extension(extension)` accepts either an object implementing `init_app(app, **config)` or an app callable.

`GraphQLExtension` requires the optional `graphql-core` package. Lua-backed features require the optional Lua integration used by the application.

The package also ships `night_mcp.py`, which is dependency-free but intentionally separate from `night.py` so the ASGI core remains a single-file module.

## JSON-RPC

Register methods with:

```python
@app.rpc("add")
def add(a, b):
    return a + b
```

Night installs `/rpc` as a JSON-RPC 2.0 POST endpoint when the first method is registered.

## Model Context Protocol

The same RPC registry can be exposed as stateless MCP 2026-07-28 tools:

```python
from night_mcp import enable_mcp

mcp = enable_mcp(app)

@mcp.tool(description="Multiply two integers")
def multiply(a: int, b: int):
    return {"value": a * b}
```

Existing `@app.rpc(...)` methods are included automatically in `tools/list`.

`night_mcp` currently implements:

- `server/discover`
- `tools/list`
- `tools/call`
- MCP HTTP header/body consistency checks
- generated tool input schemas from Python signatures
- sync and async tool calls
- tool execution errors as `isError` results

See [the MCP guide](../guides/mcp.md) for protocol and deployment details.

## Cloudflare Workers RPC

Inside Cloudflare Python Workers, the same registry can be exposed through Service Bindings:

```python
class Default(WorkerEntrypoint):
    async def night_rpc(self, method, args=None, kwargs=None):
        return await app.cloudflare_rpc(method, args, kwargs)
```

The bridge uses `workers.rpc.python_from_rpc()` and `python_to_rpc()` from `workers-runtime-sdk`. Keep Workers-specific code in the Worker entrypoint so normal Night applications remain dependency-free.

The MCP endpoint is independent of Workers RPC: it is an ordinary HTTP route and can therefore run under standard ASGI, Cloudflare Workers, or Vercel Functions.

## Benchmarks

`benchmarks/fast_path.py` contains development benchmarks for:

- Night internal route hot paths
- static routes
- one dynamic route
- large dynamic route tables
- rough in-process comparisons against other Python web frameworks when their optional benchmark dependencies are installed

When changing routing, dispatch, Request/Response construction, or TestClient internals, run both the full test suite and the benchmark before merging. Prefer same-runner A/B comparisons over comparing absolute timings from different machines.
