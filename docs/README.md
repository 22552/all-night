# Night documentation

Night is a single-file ASGI framework for Python 3.11+. The public package is `all-night`; applications import the `night` module. Optional integrations such as MCP live beside the core so `night.py` itself stays dependency-free.

日本語版は [日本語ドキュメント](ja/README.md) を参照してください。

## Start here

- [Quickstart](getting-started/quickstart.md) — install from PyPI, run the CLI or an ASGI server, and write a first application
- [HTTP applications](guides/http.md) — routing, fluent registration, requests, responses, gzip file handlers, forms, validation, cookies, and streaming
- [Templates](guides/templates.md) — `${{ ... }}` interpolation, if/for/include, restricted expressions, filters, and extension hooks
- [Node.js runtime](guides/node.md) — officially supported Node 22/24 hosting through Pyodide and Web-standard Request/Response
- [Midnight: Python ↔ HTML bridge](guides/midnight.md)
- [Browser Night](guides/browser.md) — run Night inside a browser with Pyodide and persistent runtime caching
- [Model Context Protocol](guides/mcp.md) — expose Night RPC methods as stateless MCP 2026-07-28 tools
- [Cloudflare Python Workers](guides/cloudflare-workers.md) — `cloudflare_fetch`, Workers RPC, Service Bindings, KV, and deployment notes
- [Security](guides/security.md) — sessions, cookies, CSRF, and trusted Lua macros
- [Realtime](guides/realtime.md) — SSE, WebSocket, lifespan, and streaming

## Reference

- [Application and routing](reference/application.md)
- [Request and response API](reference/request-response.md)
- [SQLite ORM](reference/orm.md)
- [CLI, testing, RPC, and extensions](reference/tooling.md)
- [Deployment notes](operations/deployment.md)
- [Vercel Functions](operations/vercel.md)
- [Netlify Functions](operations/netlify.md)

## Runtime model

Night keeps its normal CPython core dependency-free. Optional integrations such as `uvicorn`, `graphql-core`, `lupa`, Cloudflare's `workers-runtime-sdk`, and the bundled `night_mcp` extension are installed or imported only when needed.

Routing work is front-loaded at registration time: Night indexes static routes, specializes common dynamic routes, classifies endpoint call shapes, and compiles route-specific invokers. Request-time routing therefore avoids linear scans for the common route shapes used by REST APIs.

The portable Web path keeps transport-specific work outside that routing core. Node.js and Netlify use `night_node.mjs` + Pyodide + `night_web`; Browser Night uses the same `night_web` request bridge inside the tab.

## Serverless and edge

- **Cloudflare Python Workers** — Night provides a direct Request/Response bridge and Workers RPC integration.
- **Vercel Functions** — Vercel's Python runtime accepts Night directly as an ASGI `app`; see the Vercel deployment template under `deploy/vercel-night`.
- **Node.js 22 / 24** — officially tested Node runtime through `night_node.mjs` and Pyodide.
- **Netlify Functions / Node 24** — officially tested modern Request/Response Function wrapper; see `deploy/netlify-night`.
- **Browser / Pyodide** — Browser Night executes the same application locally in the tab through `night_web`; a service worker caches versioned Pyodide runtime assets between visits.
- **MCP** — the stateless MCP endpoint is an ordinary Night HTTP route, so the same MCP server can run under standard ASGI, Cloudflare Workers, Vercel Functions, or other adapters that carry normal Night HTTP routes.

## Cloudflare note

Cloudflare Python Workers run on Pyodide inside Workers isolates. Cloudflare performs top-level Python imports and initialization during deployment and snapshots WebAssembly linear memory to reduce cold-start work. Night's Workers integration is designed around that runtime: application and route registration stay at module scope, while request state remains request-scoped.

Python Workers are currently beta and require the `python_workers` compatibility flag. Check Cloudflare's current documentation when changing compatibility dates, flags, runtime SDK APIs, or deployment tooling.

## Version

The current PyPI release documented here is **all-night 0.1.2** and requires Python **3.11+**. Node/Netlify support on `main` may be newer than the latest PyPI package release.

For coding agents, see the repository-level [`SKILL.md`](../SKILL.md).