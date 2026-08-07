# All-Night

**Night** is a tiny, single-file ASGI web framework for Python 3.11+.

It keeps the core dependency-free, supports sync and async handlers, and includes routing, request/response helpers, validation, sessions, testing, realtime APIs, JSON-RPC, OpenAPI, a small SQLite ORM, and direct Cloudflare Python Workers integration.

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

- **Single-file core** — the published package is centered on `night.py` and has no required runtime dependencies on normal CPython.
- **Fast routing** — static routes use direct indexes; common dynamic routes are compiled into specialized fast paths so large route tables do not require linear scans.
- **Sync + async** — handlers are classified at registration time and Night compiles route-specific invokers to reduce per-request branching.
- **HTTP batteries included** — JSON, forms, multipart uploads, cookies, sessions, CSRF helpers, streaming, SSE, WebSocket, static files, middleware, hooks, and error handlers.
- **Typed request bodies** — validate nested dataclasses, optional values, and `list[T]` request bodies.
- **Tooling** — built-in in-process `TestClient`, CLI, named routes, OpenAPI generation, extensions, JSON-RPC, and a lightweight SQLite ORM.
- **Cloudflare Python Workers** — `Night.cloudflare_fetch()` bridges Workers Requests into Night, while `Night.cloudflare_rpc()` exposes the same `@app.rpc(...)` registry over Workers RPC/Service Bindings. Cloudflare-specific imports stay optional outside Workers.

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

## Documentation

- [Documentation index](docs/README.md)
- [Quickstart](docs/getting-started/quickstart.md)
- [HTTP guide](docs/guides/http.md)
- [Cloudflare Workers](docs/guides/cloudflare-workers.md)
- [Deployment](docs/operations/deployment.md)
- [API reference](docs/reference/application.md)
- [日本語ドキュメント](docs/ja/README.md)

For coding agents and automated tooling, see [`SKILL.md`](SKILL.md).

## Version

Current PyPI release: **0.1.1**.

Night is alpha software. Benchmark numbers in this repository are development measurements; in-process test clients do different bookkeeping and should not be treated as production HTTP throughput results.
