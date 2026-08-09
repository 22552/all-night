# Cloudflare Python Workers

## Standard profile and Workers

`all-night[standard]` includes `workers-runtime-sdk` on Python 3.13+ so local CPython development can share Cloudflare runtime types with the rest of the full Night stack. For deployment, Cloudflare Python Workers use Pyodide rather than Uvicorn, so `app.fast()`'s `uvloop`/`httptools` path is intentionally not used inside Workers.

A Workers project should keep the runtime dependency small and use Cloudflare's current toolchain:

```toml
[project]
dependencies = ["all-night==0.1.5"]

[dependency-groups]
dev = ["workers-py", "workers-runtime-sdk"]
```

Use `uv run pywrangler dev` and `uv run pywrangler deploy` for local development and deployment.

Night can run directly inside Cloudflare Python Workers without a separate ASGI server process.

Cloudflare Python Workers execute Python through Pyodide inside the Workers runtime. The platform runs top-level module initialization during deployment and snapshots WebAssembly linear memory, which means imports, `app = Night()`, and route registration are good candidates for module scope. Request-specific data must still stay request-scoped.

Python Workers are currently beta. Check Cloudflare's current documentation before changing compatibility dates, flags, or Python Workers tooling.

## Template

A complete example lives in `deploy/cloudflare-night`.

The essential shape is:

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

`Night.cloudflare_fetch()` converts the Workers `Request` into Night's HTTP path and converts the Night response back into a Workers `Response`.

Night imports Cloudflare-specific SDK objects only when the Cloudflare bridge is used, so ordinary CPython applications do not gain a mandatory Workers dependency.

## Runtime SDK

Cloudflare's `workers-runtime-sdk` provides the Python Workers runtime API, type hints, FFI wrappers, and RPC conversion helpers. With `pywrangler`, the runtime SDK is included automatically; adding it to the project configuration is useful for editor type information and explicit development environments.

Night uses the official runtime SDK's RPC conversion layer rather than implementing a separate Python/JavaScript serializer.

## Workers RPC

Night's HTTP JSON-RPC registry and Workers RPC bridge share the same methods:

```python
@app.rpc("add")
def add(a: int, b: int):
    return a + b
```

The HTTP endpoint is available through Night's `/rpc` JSON-RPC route. A Python Worker entrypoint can expose the same registry to a Service Binding:

```python
class Default(WorkerEntrypoint):
    async def fetch(self, request):
        return await app.cloudflare_fetch(request)

    async def night_rpc(self, method, args=None, kwargs=None):
        return await app.cloudflare_rpc(method, args, kwargs)
```

`cloudflare_rpc()` uses `workers.rpc.python_from_rpc()` for incoming RPC values and `workers.rpc.python_to_rpc()` for return values. Functions, RPC stubs, and other values supported by the runtime SDK therefore stay under Cloudflare's conversion rules.

## Bindings

Bindings are available from the `WorkerEntrypoint` environment. The repository's ToDo example uses Workers KV:

```python
_kv = None

class Default(WorkerEntrypoint):
    async def fetch(self, request):
        global _kv
        _kv = self.env.TODOS
        return await app.cloudflare_fetch(request)
```

For larger applications, prefer an explicit application/service object instead of broad mutable module globals. Never store per-request user state globally: a Worker isolate can serve multiple requests over its lifetime.

## Request bodies

The current `cloudflare_fetch()` bridge reads non-GET/HEAD request bodies before entering Night and enforces `app.max_body_size` after reading. Night's default body limit is 16 MiB.

For applications that expect large uploads, keep the body limit conservative and be aware that buffering consumes Worker memory. A future streaming adapter can feed chunks into Night's existing ASGI-style `Request.body()` loop without changing endpoint APIs.

## Cold-start guidance

Cloudflare already moves much Python initialization to deployment by snapshotting the initialized Pyodide memory image. For Night applications:

- define `app = Night()` at module scope;
- register routes at module scope so routing indexes and compiled invokers are part of initialized state;
- import deterministic SDK helpers at module scope only when the Worker actually uses them;
- do not perform network requests, binding I/O, or request-specific work during module initialization;
- keep the first-request bridge thin and measure first-hit, second-hit, and steady-state latency separately.

## Development and deployment

Cloudflare's current Python Workers workflow uses `pywrangler` for local development and deployment. The repository template also contains a pinned compatibility configuration that is tested in CI; do not update its compatibility date casually because Python/Pyodide runtime changes can affect behavior.

Typical commands in a Python Workers project are:

```bash
uv run pywrangler dev
uv run pywrangler deploy
```

The repository's template build is validated by CI alongside Python 3.11, 3.12, and 3.13 tests.

## References

- Cloudflare Python Workers documentation: https://developers.cloudflare.com/workers/languages/python/
- How Python Workers work and deployment snapshots: https://developers.cloudflare.com/workers/languages/python/how-python-workers-work/
- Workers RPC: https://developers.cloudflare.com/workers/runtime-apis/rpc/
