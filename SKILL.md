---
name: all-night
summary: Build, review, optimize, test, and deploy applications using the Night single-file ASGI framework.
---

# All-Night / Night

Use this skill when working with the `all-night` PyPI package or the `22552/all-night` repository: creating Night applications, modifying `night.py`, reviewing routing/request/response behavior, benchmarking performance, publishing releases, or deploying Night to Cloudflare Python Workers.

## Current baseline

- Package: `all-night`
- Import: `night`
- Current documented release: `0.1.1`
- Supported Python: `>=3.11`
- Core architecture: single-file `night.py`
- Normal CPython core: no required runtime dependencies
- Application protocol: ASGI

Before changing behavior, read `README.md`, `docs/README.md`, and the relevant reference/guide. Treat `night.py` as the source of truth when documentation and code disagree.

## Build an application

Prefer the smallest Night-native form:

```python
from night import Night

app = Night()

@app.get("/")
def index():
    return {"hello": "night"}
```

Use sync handlers when no awaitable work is needed. Use async handlers for async I/O.

Common dynamic routes:

```python
@app.get("/users/<int:user_id>")
def user(user_id: int):
    return {"id": user_id}
```

Return plain `dict`/`list` for JSON, `str` for text, `bytes` for binary content, or explicit response classes when status/headers/content type matter.

## Preserve the dependency boundary

Do not add mandatory third-party runtime dependencies to the normal Night core without a compelling reason.

Optional integrations belong behind lazy imports or application-level dependencies. Existing examples include:

- ASGI servers such as Uvicorn/Hypercorn
- `graphql-core`
- Lua integration
- Cloudflare `workers-runtime-sdk`
- optional JSON serializers such as `orjson`

A feature that only applies to one platform should not make ordinary `import night` require that platform's SDK.

## Routing and hot-path rules

Night is optimized by moving work to route-registration time.

Important structures include static method/path indexes, dynamic prefix indexes, terminal dynamic indexes, compiled regex fallback, route call classification, and route-specific invokers.

When optimizing routing:

1. preserve static-route O(1)-style lookup behavior;
2. avoid linear scans over all routes for common REST paths;
3. specialize common `<int:name>` / `<name>` shapes before falling back to regex;
4. prefer registration-time compilation over request-time introspection;
5. do not add benchmark-only caches that make repeated fixed paths unrealistically fast;
6. keep complex-pattern compatibility through the generic fallback.

Do not assume an optimization is faster. Measure it against the same baseline on the same runner/process when practical.

## Request/response rules

`Request` is a slotted dataclass. Keep frequently accessed request state cheap and lazy.

- Avoid copying ASGI `scope` unless mutation is required.
- Keep header decoding lazy; `header()` should not force decoding every header.
- Reuse cached request bodies and parsed values.
- Enforce `max_body_size` consistently.
- Avoid per-request allocations on empty middleware/hook paths.

`Response` automatically supplies common headers. The Date header uses a one-second cache; do not replace it with per-response datetime formatting.

`JSONResponse` must continue accepting the standard library serializer and alternate serializers that may return `bytes` (for example `orjson.dumps`).

## TestClient

Use a context manager when possible:

```python
with app.test_client() as client:
    response = client.get("/")
```

`TestClient` reuses `asyncio.Runner`; do not regress to `asyncio.run()` per request.

Cross-framework TestClient numbers are rough development comparisons because clients perform different bookkeeping. Never describe them as production HTTP throughput benchmarks.

## Performance workflow

For performance-sensitive changes:

1. run the full tests;
2. run `benchmarks/fast_path.py`;
3. compare static, one-dynamic-route, and large-dynamic-route cases;
4. profile full request handling if internal router timings improve but client timings regress;
5. use same-runner A/B measurements for small changes;
6. reject changes that improve one microbenchmark but introduce meaningful regressions elsewhere unless the tradeoff is explicit.

Profile before making large structural changes. Typical areas to inspect are routing, route invocation, Request construction, middleware/hooks, response coercion, serialization, and adapters.

## Cloudflare Python Workers

Read `docs/guides/cloudflare-workers.md` before modifying Cloudflare support.

Night exposes:

```python
await app.cloudflare_fetch(request)
await app.cloudflare_rpc(method, args, kwargs)
```

The Worker entrypoint normally extends `workers.WorkerEntrypoint`.

Cloudflare-specific rules:

- Python Workers currently run through Pyodide in Workers isolates.
- Cloudflare performs deployment-time top-level initialization and snapshots initialized WebAssembly memory.
- Keep deterministic `app = Night()` construction and route registration at module scope.
- Never place request-specific user state in module globals.
- Do not perform network/binding I/O during snapshot-oriented module initialization.
- Use Cloudflare's official `workers-runtime-sdk` conversion layer for RPC values; do not build a competing serializer in Night.
- Treat compatibility dates/flags as runtime changes: verify current Cloudflare docs and test the template before updating them.
- Be careful with request/response buffering because Workers have finite isolate memory.

The repository template is `deploy/cloudflare-night` and its build must stay green.

## Workers RPC

`@app.rpc("name")` is shared by Night's HTTP JSON-RPC endpoint and `cloudflare_rpc()`.

```python
@app.rpc("add")
def add(a, b):
    return a + b
```

For Workers RPC, conversion must remain delegated to `workers.rpc.python_from_rpc` and `workers.rpc.python_to_rpc`.

## Validation and compatibility

When changing endpoint call behavior, cover at least:

- sync no-argument endpoints
- async endpoints
- direct path parameters
- request positional injection
- request keyword injection
- dataclass body models
- before/after hooks
- middleware
- error handlers
- HEAD/OPTIONS behavior

When changing routing, cover method mismatch/405 and regex fallback as well as fast paths.

## Documentation

If public behavior changes, update:

- root `README.md` for user-visible positioning/setup;
- `docs/README.md` index when adding/removing guides;
- the relevant English guide/reference;
- Japanese docs when the change affects setup/deployment/core usage;
- this `SKILL.md` when agent-facing architecture or workflow changes.

Keep `docs/README.md` canonical. `docs/readme.md` exists only for compatibility with old lowercase links.

## Release

The package version is declared in `pyproject.toml`.

Before publishing:

1. increment the version;
2. run Python 3.11/3.12/3.13 CI;
3. run benchmarks and the Cloudflare template build;
4. build wheel + sdist and run `twine check`;
5. ensure the target version is not already on PyPI;
6. publish through the repository's PyPI workflow;
7. update README/docs if the documented current release changes.

Never commit PyPI credentials.

## Completion checklist

For repository changes, report:

- what changed;
- tests/CI status;
- benchmark impact for performance work;
- Cloudflare template status when relevant;
- PR/merge/release state when applicable.
