---
name: all-night
summary: Build, review, optimize, test, package, release, and deploy applications using the Night ASGI framework, its standard performance profile, Midnight, MCP, and serverless/edge integrations.
---

# All-Night / Night

Use this skill when working with the `all-night` PyPI package or the `22552/all-night` repository: creating Night applications, modifying `night.py`, reviewing routing/request/response behavior, benchmarking performance, publishing releases, using `app.fast()`, working with Midnight, exposing MCP tools, or deploying Night to Cloudflare Python Workers, Vercel Functions, Node.js, Browser Night, or Netlify Functions.

## Current baseline

- Core package: `all-night`
- Core import: `night`
- MCP extension import: `night_mcp`
- Midnight package: `all-night-midnight`
- Midnight imports: `night_midnight`, `night_midnight_component`, `night_midnight_dev`, `night_midnight_form`
- Current documented PyPI release: `0.1.5`
- Supported Python: `>=3.11`
- Core architecture: single-file `night.py`
- Minimal CPython core: no required runtime dependencies
- Application protocol: ASGI
- Recommended full install: `all-night[standard]`

Before changing behavior, read `README.md`, `docs/README.md`, and the relevant reference/guide. Treat implementation code as the source of truth when documentation and code disagree.

## Install profiles

Night has two user-facing install profiles.

Minimal core:

```bash
python -m pip install -U all-night
```

This keeps ordinary CPython Night dependency-free and does not include Midnight modules.

Recommended standard profile:

```bash
python -m pip install -U "all-night[standard]"
```

The standard profile currently pulls in the recommended CPython/server stack, including:

- `uvicorn[standard]`
- `orjson`
- `all-night-midnight==0.1.5`
- `workers-runtime-sdk` on supported Python versions for Cloudflare-oriented development

Do not move standard-only dependencies into the minimal core unless the project explicitly changes its dependency policy.

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

## Fast mode

Night 0.1.5 adds the optional CPython fast profile:

```python
from night import Night

app = Night().fast()
```

`Night.fast()`:

- returns the same application instance;
- requires the standard profile;
- switches dict/list response serialization to `orjson`;
- sets the application's fast-mode flag;
- when launched with `night run`, lets Night explicitly select installed Uvicorn fast backends such as `uvloop`, `httptools`, and `websockets`.

`app.fast()` does not override backend choices made by an external ASGI server. If the user launches `uvicorn app:app` directly, Uvicorn remains responsible for loop/protocol selection.

Fast mode is a CPython/server optimization. Do not claim that `uvloop` or `httptools` apply inside Cloudflare Python Workers, Browser Night, or other Pyodide runtimes.

## Preserve the dependency boundary

Do not add mandatory third-party runtime dependencies to the normal Night core without a compelling reason.

Optional integrations belong behind lazy imports, extras, separate distributions, optional modules, or application-level dependencies. Existing examples include:

- `all-night[standard]`
- `all-night-midnight`
- ASGI servers such as Uvicorn/Hypercorn
- `graphql-core`
- Lua integration
- Cloudflare `workers-runtime-sdk`
- optional JSON serializers such as `orjson`
- `night_mcp`, which stays outside the single-file `night.py` core

A feature that only applies to one platform must not make ordinary `import night` require that platform's SDK.

## Midnight packaging

Midnight is not bundled into the minimal `all-night` wheel as of 0.1.5.

The separate distribution `all-night-midnight` provides:

- `night_midnight.py`
- `night_midnight_component.py`
- `night_midnight_dev.py`
- `night_midnight_form.py`

Users normally receive it through:

```bash
python -m pip install -U "all-night[standard]"
```

When editing packaging, preserve the wheel boundary:

- the core `all-night` wheel must not contain `night_midnight*` modules;
- the `all-night-midnight` wheel must contain all intended Midnight modules;
- `all-night[standard]` must resolve the matching Midnight release.

Read `docs/guides/midnight.md` before changing Midnight APIs or packaging.

## Routing and hot-path rules

Night is optimized by moving work to route-registration time and minimizing request-path allocations.

Important structures include static method/path indexes, dynamic prefix indexes, terminal dynamic indexes, compiled regex fallback, route call classification, and route-specific invokers.

Recent routing/performance work removed an unused composite dynamic matcher rebuild that caused unnecessary O(n)-style reconstruction during route registration. Do not reintroduce registration-time structures unless they are actually used by dispatch.

When optimizing routing:

1. preserve static-route O(1)-style lookup behavior;
2. avoid linear scans over all routes for common REST paths;
3. specialize common `<int:name>` / `<name>` shapes before falling back to regex;
4. prefer registration-time compilation over request-time introspection;
5. avoid rebuilding indexes that request dispatch does not consume;
6. do not add benchmark-only caches that make repeated fixed paths unrealistically fast;
7. keep complex-pattern compatibility through the generic fallback.

Do not assume an optimization is faster. Measure it against the same baseline on the same runner/process when practical.

## Template performance

Night templates compile their structure ahead of rendering. Expression AST parsing should also stay out of the render hot path.

Current performance expectations:

- parse template expressions at compile time and cache the resulting AST nodes;
- do not call `ast.parse()` for the same expression on every render;
- use a fast path when an expression contains no filters before entering character-by-character filter splitting;
- keep semantics identical between cached and uncached evaluation paths.

Template optimizations should be measured with a dedicated render microbenchmark as well as application-level tests.

## Request/response rules

`Request` is a slotted dataclass. Keep frequently accessed request state cheap and lazy.

- Avoid copying ASGI `scope` unless mutation is required.
- Keep header decoding lazy; `header()` should not force decoding every header.
- Reuse cached request bodies and parsed values.
- Enforce `max_body_size` consistently.
- Avoid per-request allocations on empty middleware/hook paths.
- Avoid unnecessary repeated `setdefault()` or dictionary construction for request state.

`Response` automatically supplies common headers. The Date header uses a one-second cache; do not replace it with per-response datetime formatting.

The common response path has explicit no-custom-header fast paths. Preserve them when changing `Response`, `JSONResponse`, `PlainTextResponse`, or `HTMLResponse`.

`JSONResponse` must continue accepting the standard library serializer and alternate serializers that may return `bytes`. `app.fast()` depends on this for `orjson.dumps`.

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
2. run `benchmarks/fast_path.py` when applicable;
3. compare static, one-dynamic-route, and large-dynamic-route cases;
4. add a focused microbenchmark for template, response, or registration work when relevant;
5. profile full request handling if internal router timings improve but client timings regress;
6. use same-runner A/B measurements for small changes;
7. reject changes that improve one microbenchmark but introduce meaningful regressions elsewhere unless the tradeoff is explicit.

Profile before making large structural changes. Typical areas to inspect are routing, route invocation, Request construction, middleware/hooks, response coercion, serialization, templates, and adapters.

Do not compare short GitHub-hosted runs from different runners as if a few-percent difference were conclusive. For small changes, baseline and candidate should run on the same runner.

## MCP 2026-07-28

Read `docs/guides/mcp.md` before changing MCP support.

MCP lives in `night_mcp.py` and exposes Night's existing `app.rpc_methods` registry over an HTTP route.

```python
from night_mcp import enable_mcp

mcp = enable_mcp(app)

@mcp.tool()
def add(a: int, b: int):
    return {"value": a + b}
```

Existing `@app.rpc("name")` callables must remain visible as MCP tools.

Current MCP scope:

- protocol revision `2026-07-28`;
- stateless HTTP core;
- `server/discover`;
- `tools/list`;
- `tools/call`;
- generated input schemas from Python signatures;
- sync and async tools;
- cache hints on discovery/list responses.

MCP rules:

- Do not reintroduce the removed protocol-level initialize/session requirement for the 2026-07-28 path.
- Validate `MCP-Protocol-Version` and mirrored `Mcp-Method` / applicable `Mcp-Name` headers against the JSON-RPC body.
- Use MCP error code `-32020` for header/body mismatches.
- Put server identity in response `_meta.io.modelcontextprotocol/serverInfo`.
- Keep `ttlMs` / `cacheScope` semantics explicit; default to `private` unless sharing is safe.
- Treat unknown tools and invalid call arguments as protocol errors; tool-body failures should remain tool results with `isError: true`.
- Do not add the official MCP SDK as a mandatory dependency merely to implement the small transport surface Night already owns.
- If adding resources, prompts, Tasks, subscriptions, authorization, MRTR, or older protocol revisions, verify the current MCP specification first because the protocol evolves quickly.

## Cloudflare Python Workers

Read `docs/guides/cloudflare-workers.md` before modifying Cloudflare support.

Night exposes:

```python
await app.cloudflare_fetch(request)
await app.cloudflare_rpc(method, args, kwargs)
```

The Worker entrypoint normally extends `workers.WorkerEntrypoint`.

Cloudflare-specific rules:

- Python Workers run through Pyodide in Workers isolates.
- Cloudflare performs deployment-time top-level initialization and snapshots initialized WebAssembly memory.
- Keep deterministic `app = Night()` construction and route registration at module scope.
- Never place request-specific user state in module globals.
- Do not perform network/binding I/O during snapshot-oriented module initialization.
- Use Cloudflare's official `workers-runtime-sdk` conversion layer for Workers RPC values; do not build a competing serializer in Night.
- `all-night[standard]` may install `workers-runtime-sdk` for local/full-stack development, but production Workers projects should still follow the Workers-native dependency/tooling guidance in the docs.
- `app.fast()` does not make Workers use Uvicorn, `uvloop`, or `httptools`.
- Treat compatibility dates/flags as runtime changes: verify current Cloudflare docs and test the template before updating them.
- Be careful with request/response buffering because Workers have finite isolate memory.

The repository template is `deploy/cloudflare-night` and its build must stay green.

## Workers RPC

`@app.rpc("name")` is shared by Night's HTTP JSON-RPC endpoint, `cloudflare_rpc()`, and the MCP extension.

```python
@app.rpc("add")
def add(a, b):
    return a + b
```

For Workers RPC, conversion must remain delegated to `workers.rpc.python_from_rpc` and `workers.rpc.python_to_rpc`.

## Vercel Functions

Read `docs/operations/vercel.md` before changing Vercel support.

Vercel's Python runtime accepts an `app` variable exposing an ASGI application. Therefore Night should normally be deployed directly:

```python
from night import Night

app = Night()
```

Vercel rules:

- Do not create a proprietary request/response adapter when standard ASGI already works.
- Use a recognized Python entrypoint or `[tool.vercel] entrypoint = "..."`.
- Keep Vercel configuration in deployment templates/docs instead of adding Vercel runtime imports to `night.py`.
- Declare a Vercel-supported Python version in deployment examples.
- Keep bundle contents and dependencies small; Python functions bundle reachable project files.
- Streaming should remain standard ASGI streaming rather than a Night-specific Vercel API.
- The template under `deploy/vercel-night` must stay importable and its basic routes must pass tests.

MCP on Vercel is just the same Night `/mcp` HTTP route; do not fork the MCP implementation by platform.

## Browser Night, Node.js, and Netlify

Read the relevant guides before changing these runtimes:

- `docs/guides/browser.md`
- `docs/guides/node.md`
- `docs/operations/netlify.md`

Browser Night uses Pyodide and Web-standard request/response adaptation. Node.js support uses the shared Pyodide adapter. Netlify Functions use the Node runtime adapter rather than a separate Night HTTP implementation.

Do not make CPython-specific fast-mode assumptions in these runtimes.

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

When changing `app.fast()`, cover:

- return-self behavior;
- missing-standard-profile error behavior;
- dict/list serialization through the configured serializer;
- CLI backend selection only when modules are installed.

When changing Midnight packaging, build both distributions and inspect wheel contents.

When changing MCP, cover discover, list, sync call, async call, generated schema, invalid params, unknown tools, and header mismatch.

## Documentation

If public behavior changes, update:

- root `README.md` for user-visible positioning/setup;
- `docs/README.md` index when adding/removing guides;
- the relevant English guide/reference;
- Japanese docs when the change affects setup/deployment/core usage;
- this `SKILL.md` when agent-facing architecture or workflow changes.

The separate `nighthomepage` repository renders the official `all-night/main/docs` Markdown live. Update homepage-specific copy/navigation there when release positioning or navigation changes, but keep canonical documentation in `all-night/docs`.

Keep `docs/README.md` canonical. `docs/readme.md` exists only for compatibility with old lowercase links.

## Release

The core version is declared in `pyproject.toml`. The matching Midnight version is declared in `packages/midnight/pyproject.toml`.

The repository also uses `.release/version` as the release trigger/version marker.

Current release flow:

1. update the core and Midnight package versions together;
2. update `.release/version` to the target version;
3. run Python 3.11/3.12/3.13 CI plus runtime/template/deployment checks relevant to the change;
4. build both the core and Midnight distributions;
5. verify the core wheel excludes `night_midnight*` and the Midnight wheel contains all intended modules;
6. run `twine check` on all distributions;
7. merge the release changes to `main`;
8. the release-tag workflow creates `v<version>`;
9. the release workflow explicitly dispatches the PyPI publish workflow because tags pushed by `GITHUB_TOKEN` do not trigger a second workflow via normal push chaining;
10. verify the PyPI publish job succeeds for both `all-night` and `all-night-midnight`.

Do not rely on a bot-created tag push alone to trigger the publish workflow.

Ensure all intended `py-modules` are included in the correct built package. `night_mcp` belongs to the core distribution; Midnight modules belong only to `all-night-midnight`.

Never commit PyPI credentials.

## Completion checklist

For repository changes, report:

- what changed;
- tests/CI status;
- benchmark impact for performance work;
- core/standard/Midnight packaging impact when relevant;
- Cloudflare template status when relevant;
- Vercel/Node/Netlify/Browser runtime status when relevant;
- MCP protocol coverage when relevant;
- PR/merge/release state when applicable.
