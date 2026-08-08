# All-Night

**Night** is a tiny, single-file ASGI web framework for Python 3.11+ with portable Web-runtime adapters for browsers, Node.js, and serverless platforms.

It keeps the core dependency-free, supports sync and async handlers, and includes routing, request/response helpers, validation, sessions, testing, realtime APIs, JSON-RPC, OpenAPI, a small SQLite ORM, Cloudflare Python Workers integration, stateless MCP tooling, Vercel ASGI deployment, Node.js/Pyodide hosting, and Netlify Functions support.

```bash
pip install -U all-night
```

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

Run with an ASGI server:

```bash
uvicorn app:app --reload
```

or use Night's CLI:

```bash
night run app.py
```

## Why Night

- **Single-file core** — the framework core stays in `night.py` and has no required runtime dependencies on normal CPython.
- **Fast routing** — static routes use direct indexes; common dynamic routes are compiled into specialized fast paths so large route tables do not require linear scans.
- **Sync + async** — handlers are classified at registration time and Night compiles route-specific invokers to reduce per-request branching.
- **HTTP batteries included** — JSON, forms, multipart uploads, cookies, sessions, CSRF helpers, streaming, SSE, WebSocket, static files, middleware, hooks, and error handlers.
- **Typed request bodies** — validate nested dataclasses, optional values, and `list[T]` request bodies.
- **Tooling** — built-in in-process `TestClient`, CLI, named routes, OpenAPI generation, extensions, JSON-RPC, and a lightweight SQLite ORM.
- **MCP 2026-07-28** — the optional `night_mcp` module exposes the existing RPC registry as stateless `server/discover`, `tools/list`, and `tools/call` HTTP endpoints without adding runtime dependencies.
- **Cloudflare Python Workers** — `Night.cloudflare_fetch()` bridges Workers Requests into Night, while `Night.cloudflare_rpc()` exposes the same `@app.rpc(...)` registry over Workers RPC/Service Bindings. Cloudflare-specific imports stay optional outside Workers.
- **Vercel Functions** — Vercel's Python runtime accepts Night directly as an ASGI `app`; no request/response adapter is needed.
- **Node.js 22 / 24** — `night_node.mjs` runs the same Night application under Node through Pyodide and Web-standard `Request` / `Response`; both supported Node lines run in CI.
- **Netlify Functions** — the official Node 24 template uses Netlify's modern `Request -> Response` Functions API and the shared Night Node adapter.
- **Browser Night** — run Night entirely in a browser tab with Pyodide; a service worker persistently caches versioned Pyodide runtime assets after the first load.

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

Existing `@app.rpc(...)` methods are also visible as MCP tools. The first implementation targets the stateless MCP `2026-07-28` core with `server/discover`, `tools/list`, `tools/call`, header/body validation, cache hints, and server metadata.

See the [MCP guide](docs/guides/mcp.md).

## Cloudflare Workers

The repository contains a working Python Workers template under [`deploy/cloudflare-night`](deploy/cloudflare-night).

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

Night uses the official `workers-runtime-sdk` conversion layer for Workers RPC values. See the [Cloudflare Workers guide](docs/guides/cloudflare-workers.md).

## Vercel Functions

Vercel's Python runtime can serve Night directly because Night exposes a standard ASGI `app`.

```python
from night import Night

app = Night()

@app.get("/")
def index():
    return {"hello": "vercel"}
```

A ready-to-copy template lives in [`deploy/vercel-night`](deploy/vercel-night). See the [Vercel deployment guide](docs/operations/vercel.md).

## Node.js

Node.js **22 and 24** are official Night runtime targets. The shared adapter starts Pyodide once per warm Node process, loads Night and your Python application, accepts Web-standard `Request` objects, and returns Web-standard `Response` objects.

```js
import { createNightNodeHandler } from "./night_node.mjs";

const night = createNightNodeHandler({ sourceDir: "python" });
const response = await night(new Request("https://night.local/"));
console.log(response.status, await response.text());
```

Install the pinned Node dependency with `npm install`. See the [Node.js runtime guide](docs/guides/node.md).

## Netlify Functions

The official Netlify template lives in [`deploy/netlify-night`](deploy/netlify-night) and targets **Node.js 24**. The Function itself is only a thin modern Netlify wrapper around `night_node.mjs`; the build vendors Night's Python sources and the application into the Function bundle.

```bash
cd deploy/netlify-night
npm install
npm run dev
```

See the [Netlify deployment guide](docs/operations/netlify.md).

## Midnight

Browser Night includes **Midnight**, a bidirectional Python ↔ HTML bridge for DOM events, structured DOM updates, custom events, and optional WebSocket transport. See `docs/guides/midnight.md`.

## Browser Night

Night can run entirely in the browser through Pyodide and the `night_web` adapter. No Python server is required: routes execute inside the tab and Web-style requests are bridged into the same Night application.

```python
from night import Night, send_file

app = Night().gz()
app.get("/hello", lambda: {"hello": "browser"})
app.get("/data", send_file("data.json"))
```

The GitHub Pages demo lives under [`deploy/browser-night`](deploy/browser-night). Its service worker caches only versioned Pyodide CDN assets (`.mjs`, `.wasm`, package metadata, and packages such as `sqlite3`) in Cache Storage, so later starts can reuse the runtime without freezing Night's own source updates. See the [Browser Night guide](docs/guides/browser.md).

## Documentation

- [Documentation index](docs/README.md)
- [Quickstart](docs/getting-started/quickstart.md)
- [HTTP guide](docs/guides/http.md)
- [Node.js runtime](docs/guides/node.md)
- [Netlify Functions](docs/operations/netlify.md)
- [Browser Night / Pyodide](docs/guides/browser.md)
- [MCP](docs/guides/mcp.md)
- [Cloudflare Workers](docs/guides/cloudflare-workers.md)
- [Vercel Functions](docs/operations/vercel.md)
- [Deployment](docs/operations/deployment.md)
- [API reference](docs/reference/application.md)
- [日本語ドキュメント](docs/ja/README.md)

For coding agents and automated tooling, see [`SKILL.md`](SKILL.md).

## Version

Current PyPI release: **0.1.2**.

Node.js and Netlify support described above can be newer on `main` than the current PyPI package. Night is alpha software. Features merged after the latest PyPI release may exist on `main` before the next package publication. Benchmark numbers in this repository are development measurements; in-process test clients do different bookkeeping and should not be treated as production HTTP throughput results.
