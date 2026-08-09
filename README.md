# All-Night

**Night** is a tiny, single-file ASGI web framework for Python 3.11+ with portable Web-runtime adapters for browsers, Node.js, and serverless platforms.

The core stays dependency-free. The recommended `standard` profile adds the fast CPython server stack, Midnight, and Cloudflare development/runtime helpers.

## Install

Minimal dependency-free core:

```bash
pip install -U all-night
```

Recommended full install:

```bash
pip install -U "all-night[standard]"
```

`all-night[standard]` installs `uvicorn[standard]`, `orjson`, `workers-runtime-sdk`, and the separate `all-night-midnight` distribution. Starting with **0.1.5**, the `night_midnight*` modules are no longer bundled in the minimal `all-night` wheel.

```python
from night import Night

app = Night()

@app.get("/")
def index():
    return {"hello": "night"}

@app.get("/users/<int:user_id>")
def user(user_id: int):
    return {"id": user_id}
```

Run with Night's CLI:

```bash
night run app.py
```

or any ASGI server:

```bash
uvicorn app:app --reload
```


## NightCLI

`nightcli` manages a Night project through a small, portable `night.toml`.
It creates a project without forcing a hosting platform and can validate the
configured application before it is deployed.

```bash
nightcli new my-api --template api
cd my-api
nightcli check
nightcli routes
nightcli run --reload
```

Templates are `api`, `site`, `midnight`, and `cloudflare`. Use
`nightcli info` to inspect the nearest project, or pass
`--project path/to/project` from elsewhere.

## Fast mode

With the standard profile installed, enable Night's optional CPython fast path with `app.fast()`:

```python
from night import Night

app = Night().fast()

@app.get("/")
def index():
    return {"hello": "fast night"}
```

`app.fast()` switches Night's dict/list response serialization to `orjson`. When the application is launched with `night run`, Night also selects `uvloop`, `httptools`, and `websockets` when those backends are available from `uvicorn[standard]`. If you launch with an external ASGI command such as `uvicorn app:app`, that server still controls its own event loop/backend selection; Uvicorn's `auto` mode will normally use its installed standard accelerators.

## Why Night

- **Single-file core** — the framework core stays in `night.py` and has no required runtime dependencies on normal CPython.
- **Fast routing** — static routes use direct indexes; common dynamic routes are compiled into specialized fast paths so large route tables do not require linear scans.
- **Fast response path** — common JSON/text/HTML responses avoid unnecessary temporary header dictionaries and `app.fast()` can use `orjson`.
- **Sync + async** — handlers are classified at registration time and Night compiles route-specific invokers to reduce per-request branching.
- **HTTP batteries included** — JSON, forms, multipart uploads, cookies, sessions, CSRF helpers, streaming, SSE, WebSocket, static files, middleware, hooks, and error handlers.
- **Typed request bodies** — validate nested dataclasses, optional values, and `list[T]` request bodies.
- **Tooling** — built-in in-process `TestClient`, CLI, named routes, OpenAPI generation, extensions, JSON-RPC, and a lightweight SQLite ORM.
- **MCP 2026-07-28** — the optional `night_mcp` module exposes the existing RPC registry as stateless `server/discover`, `tools/list`, and `tools/call` HTTP endpoints without adding runtime dependencies.
- **Cloudflare Python Workers** — `Night.cloudflare_fetch()` bridges Workers Requests into Night, while `Night.cloudflare_rpc()` exposes the same `@app.rpc(...)` registry over Workers RPC/Service Bindings.
- **Vercel Functions** — Vercel's Python runtime accepts Night directly as an ASGI `app`; no request/response adapter is needed.
- **Node.js 22 / 24** — `night_node.mjs` runs the same Night application under Node through Pyodide and Web-standard `Request` / `Response`.
- **Netlify Functions** — the official Node 24 template uses Netlify's modern `Request -> Response` Functions API and the shared Night Node adapter.
- **Browser Night** — run Night entirely in a browser tab with Pyodide.

## MCP

```python
from night import Night
from night_mcp import enable_mcp

app = Night()
mcp = enable_mcp(app)

@mcp.tool(description="Add two integers")
def add(a: int, b: int):
    return {"value": a + b}
```

Existing `@app.rpc(...)` methods are also visible as MCP tools. See the [MCP guide](docs/guides/mcp.md).

## Cloudflare Workers

Night keeps the Workers adapter in the core package. The standard profile additionally installs `workers-runtime-sdk` on Python 3.13+ for local typing/runtime integration.

For actual Python Workers deployment, use Cloudflare's Workers-native toolchain rather than Uvicorn:

```toml
[project]
dependencies = ["all-night==0.1.5"]

[dependency-groups]
dev = [
  "workers-py",
  "workers-runtime-sdk",
]
```

```python
from night import Night
from workers import WorkerEntrypoint

app = Night()

@app.get("/")
def index():
    return {"hello": "edge"}

class Default(WorkerEntrypoint):
    async def fetch(self, request):
        return await app.cloudflare_fetch(request)
```

Cloudflare Python Workers run inside Pyodide, so `app.fast()`'s CPython `uvloop`/`httptools` path is not used there. See the [Cloudflare Workers guide](docs/guides/cloudflare-workers.md).

## Midnight

Midnight is Night's bidirectional Python ↔ HTML bridge for DOM events, structured DOM updates, custom events, forms, reusable components, and optional WebSocket transport.

Since **0.1.5**, Midnight is installed through the standard profile:

```bash
pip install -U "all-night[standard]"
```

This pulls the separate `all-night-midnight` wheel, which provides `night_midnight`, `night_midnight_component`, `night_midnight_dev`, and `night_midnight_form`. See the [Midnight guide](docs/guides/midnight.md).

## Browser Night

Night can run entirely in the browser through Pyodide and the `night_web` adapter. No Python server is required: routes execute inside the tab and Web-style requests are bridged into the same Night application.

The GitHub Pages demo lives under [`deploy/browser-night`](deploy/browser-night). See the [Browser Night guide](docs/guides/browser.md).

## Deployment

- **Normal ASGI / CPython** — Uvicorn, Hypercorn, or another ASGI server
- **Vercel Functions** — direct ASGI application
- **Cloudflare Python Workers** — Workers-native `cloudflare_fetch()` bridge
- **Node.js 22 / 24** — Pyodide + `night_node.mjs`
- **Netlify Functions** — Node adapter and Web-standard Request/Response
- **Browser Night** — Pyodide inside the browser tab

See [Deployment](docs/operations/deployment.md).

## Documentation

Start with the **[documentation index](docs/README.md)**.

Recommended reading order:

1. [Quickstart](docs/getting-started/quickstart.md)
2. [HTTP guide](docs/guides/http.md)
3. [Application and routing reference](docs/reference/application.md)
4. [Request / Response reference](docs/reference/request-response.md)
5. [Tooling and CLI](docs/reference/tooling.md)
6. [Deployment](docs/operations/deployment.md)

Additional guides:

- [Templates](docs/guides/templates.md)
- [Realtime / WebSocket / SSE](docs/guides/realtime.md)
- [Midnight](docs/guides/midnight.md)
- [Browser Night / Pyodide](docs/guides/browser.md)
- [Node.js runtime](docs/guides/node.md)
- [MCP](docs/guides/mcp.md)
- [Cloudflare Workers](docs/guides/cloudflare-workers.md)
- [Vercel Functions](docs/operations/vercel.md)
- [Netlify Functions](docs/operations/netlify.md)
- [日本語ドキュメント](docs/ja/README.md)

For coding agents and automated tooling, see [`SKILL.md`](SKILL.md).

## Version

Current release target: **0.1.5**. Night requires Python **3.11+**.

Night is alpha software. Benchmark numbers in this repository are development measurements; in-process test clients do different bookkeeping and should not be treated as production HTTP throughput results.
