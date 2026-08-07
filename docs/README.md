# Night documentation

Night is a single-file ASGI framework for Python 3.11+. The public package is `all-night`; applications import the `night` module. Optional integrations such as MCP live beside the core so `night.py` itself stays dependency-free.

日本語版は [日本語ドキュメント](ja/README.md) を参照してください。

## Start here

- [Quickstart](getting-started/quickstart.md) — install from PyPI, run the CLI or an ASGI server, and write a first application
- [HTTP applications](guides/http.md) — routing, requests, responses, forms, files, validation, cookies, and streaming
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

## Runtime model

Night keeps its normal CPython core dependency-free. Optional integrations such as `uvicorn`, `graphql-core`, `lupa`, Cloudflare's `workers-runtime-sdk`, and the bundled `night_mcp` extension are installed or imported only when needed.

Routing work is front-loaded at registration time: Night indexes static routes, specializes common dynamic routes, classifies endpoint call shapes, and compiles route-specific invokers. Request-time routing therefore avoids linear scans for the common route shapes used by REST APIs.

## Serverless and edge

- **Cloudflare Python Workers** — Night provides a direct Request/Response bridge and Workers RPC integration.
- **Vercel Functions** — Vercel's Python runtime accepts Night directly as an ASGI `app`; see the Vercel deployment template under `deploy/vercel-night`.
- **MCP** — the stateless MCP endpoint is an ordinary Night HTTP route, so the same MCP server can run under standard ASGI, Cloudflare Workers, or Vercel Functions.

## Cloudflare note

Cloudflare Python Workers run on Pyodide inside Workers isolates. Cloudflare performs top-level Python imports and initialization during deployment and snapshots WebAssembly linear memory to reduce cold-start work. Night's Workers integration is designed around that runtime: application and route registration stay at module scope, while request state remains request-scoped.

Python Workers are currently beta and require the `python_workers` compatibility flag. Check Cloudflare's current documentation when changing compatibility dates, flags, runtime SDK APIs, or deployment tooling.

## Version

The current PyPI release documented here is **all-night 0.1.1** and requires Python **3.11+**. Features on `main` can be newer than the latest package release.

For coding agents, see the repository-level [`SKILL.md`](../SKILL.md).
