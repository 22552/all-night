# Night documentation

Night is a single-file ASGI framework for Python 3.11+. The public package is `all-night`; applications import the `night` module.

日本語版は [日本語ドキュメント](ja/README.md) を参照してください。

## Start here

- [Quickstart](getting-started/quickstart.md) — install from PyPI, run the CLI or an ASGI server, and write a first application
- [HTTP applications](guides/http.md) — routing, requests, responses, forms, files, validation, cookies, and streaming
- [Cloudflare Python Workers](guides/cloudflare-workers.md) — `cloudflare_fetch`, Workers RPC, Service Bindings, KV, and deployment notes
- [Security](guides/security.md) — sessions, cookies, CSRF, and trusted Lua macros
- [Realtime](guides/realtime.md) — SSE, WebSocket, lifespan, and streaming

## Reference

- [Application and routing](reference/application.md)
- [Request and response API](reference/request-response.md)
- [SQLite ORM](reference/orm.md)
- [CLI, testing, RPC, and extensions](reference/tooling.md)
- [Deployment notes](operations/deployment.md)

## Runtime model

Night keeps its normal CPython core dependency-free. Optional integrations such as `uvicorn`, `graphql-core`, `lupa`, and Cloudflare's `workers-runtime-sdk` are installed only by applications that need them.

Routing work is front-loaded at registration time: Night indexes static routes, specializes common dynamic routes, classifies endpoint call shapes, and compiles route-specific invokers. Request-time routing therefore avoids linear scans for the common route shapes used by REST APIs.

## Cloudflare note

Cloudflare Python Workers run on Pyodide inside Workers isolates. Cloudflare performs top-level Python imports and initialization during deployment and snapshots WebAssembly linear memory to reduce cold-start work. Night's Workers integration is designed around that runtime: application and route registration stay at module scope, while request state remains request-scoped.

Python Workers are currently beta and require the `python_workers` compatibility flag. Check Cloudflare's current documentation when changing compatibility dates, flags, runtime SDK APIs, or deployment tooling.

## Version

The current PyPI release documented here is **all-night 0.1.1** and requires Python **3.11+**.

For coding agents, see the repository-level [`SKILL.md`](../SKILL.md).
