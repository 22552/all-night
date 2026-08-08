# Night documentation

Night is a tiny, single-file ASGI framework for Python **3.11+**. The PyPI package is `all-night`; applications import the `night` module.

The normal CPython core stays dependency-free. Optional integrations such as Uvicorn, GraphQL, Lua, Cloudflare Workers, MCP, Pyodide runtimes, and Midnight live around that core instead of becoming required dependencies.

日本語版は [日本語ドキュメント](ja/README.md) を参照してください。

## Start here

New to Night? Use this order:

1. [Quickstart](getting-started/quickstart.md) — install Night, create `app.py`, run it, and test it
2. [HTTP applications](guides/http.md) — routing, requests, responses, files, forms, validation, cookies, and streaming
3. [Application and routing reference](reference/application.md) — detailed `Night` and routing APIs
4. [Request and response reference](reference/request-response.md) — request parsing and response classes
5. [Tooling and CLI](reference/tooling.md) — CLI behavior, TestClient, middleware, RPC, MCP, and extensions
6. [Deployment](operations/deployment.md) — choose a runtime or hosting target

## What Night includes

### HTTP and routing

- decorator and fluent route registration
- static and dynamic routes
- typed path parameters
- automatic `HEAD` and `OPTIONS`
- named routes and URL generation
- middleware, before/after hooks, and error handlers
- JSON, text, HTML, redirects, streaming, and file responses
- forms and multipart uploads
- cookies and signed sessions
- CSRF helpers
- typed body validation
- static-file routing

Read: [HTTP applications](guides/http.md) · [Application reference](reference/application.md) · [Request/Response reference](reference/request-response.md)

### Realtime

- Server-Sent Events
- WebSocket routes
- ASGI lifespan startup/shutdown hooks
- streaming responses

Read: [Realtime](guides/realtime.md)

### Templates and browser UI

- `${{ ... }}` template interpolation
- `if`, `for`, and `include`
- restricted expressions and filters
- Midnight Python ↔ HTML bridge
- form snapshots
- reusable Midnight components
- development hot reload

Read: [Templates](guides/templates.md) · [Midnight](guides/midnight.md) · [Midnight forms](guides/midnight-forms.md) · [Midnight components](guides/midnight-components.md)

### Data and APIs

- lightweight SQLite ORM
- JSON-RPC 2.0 registry
- OpenAPI generation
- stateless MCP tool exposure through `night_mcp`
- Cloudflare Workers RPC / Service Binding bridge

Read: [SQLite ORM](reference/orm.md) · [Tooling / RPC](reference/tooling.md) · [MCP](guides/mcp.md)

## Runtime and deployment map

Night can keep the same application model across several runtimes:

| Runtime | How Night runs | Guide |
| --- | --- | --- |
| CPython / ASGI | Standard ASGI application | [Quickstart](getting-started/quickstart.md) |
| Vercel Functions | Direct ASGI `app` | [Vercel](operations/vercel.md) |
| Cloudflare Python Workers | `cloudflare_fetch()` request bridge | [Cloudflare Workers](guides/cloudflare-workers.md) |
| Node.js 22 / 24 | Pyodide + `night_node.mjs` | [Node.js](guides/node.md) |
| Netlify Functions | Node adapter + Web Request/Response | [Netlify](operations/netlify.md) |
| Browser | Pyodide + `night_web` inside the tab | [Browser Night](guides/browser.md) |

See [Deployment notes](operations/deployment.md) for the broader deployment overview.

## Browser Night

[Browser Night](guides/browser.md) runs a Night application entirely inside a browser tab using Pyodide. The same `night_web` request bridge is also used by the portable Web runtime path.

The repository's GitHub Pages deployment currently publishes the **Browser Night demo**, not this Markdown documentation tree. The documentation source of truth is `docs/` in the repository.

## CLI

Installing `all-night` exposes `night`.

```bash
night run app.py
night run app.py --host 0.0.0.0 --port 8080
```

The current 0.1.4 implementation also contains `night routes` and `night shell`, but they do not currently accept an application path. Older docs that showed `night routes app.py` or `night shell app.py` were incorrect.

Read the exact current behavior in [Tooling and CLI](reference/tooling.md).

## Reference

- [Application and routing](reference/application.md)
- [Request and response API](reference/request-response.md)
- [SQLite ORM](reference/orm.md)
- [CLI, testing, RPC, MCP, and extensions](reference/tooling.md)

## Guides

- [HTTP applications](guides/http.md)
- [Templates](guides/templates.md)
- [Realtime](guides/realtime.md)
- [Security](guides/security.md)
- [Midnight](guides/midnight.md)
- [Midnight forms](guides/midnight-forms.md)
- [Midnight components + hot reload](guides/midnight-components.md)
- [Browser Night](guides/browser.md)
- [Node.js runtime](guides/node.md)
- [MCP](guides/mcp.md)
- [Cloudflare Python Workers](guides/cloudflare-workers.md)

## Operations

- [Deployment overview](operations/deployment.md)
- [Vercel Functions](operations/vercel.md)
- [Netlify Functions](operations/netlify.md)

## Runtime model

Routing work is front-loaded at registration time. Night indexes static routes, specializes common dynamic routes, classifies endpoint call shapes, and compiles route-specific invokers. Request-time routing therefore avoids linear scans for common route shapes used by REST APIs.

The portable Web path keeps transport-specific work outside that routing core. Node.js and Netlify use `night_node.mjs` + Pyodide + `night_web`; Browser Night uses the same `night_web` request bridge inside the tab.

## Optional dependencies

The framework core has no required runtime dependencies on normal CPython. Install optional packages only for the features you use. Examples include:

- `uvicorn` — serving with `night run` or Uvicorn directly
- `graphql-core` — GraphQL extension
- `lupa` — Lua-backed features
- `workers-runtime-sdk` — Cloudflare Workers integration

`night_mcp` is bundled with `all-night` but intentionally kept outside `night.py`.

## Version

The current PyPI release documented here is **all-night 0.1.4**, requiring Python **3.11+**.

Midnight is bundled as part of `all-night` through the modules `night_midnight`, `night_midnight_component`, `night_midnight_dev`, and `night_midnight_form`; it is not a separate PyPI distribution.

For coding agents, see the repository-level [`SKILL.md`](../SKILL.md).
