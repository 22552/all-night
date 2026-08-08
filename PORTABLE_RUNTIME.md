# Portable runtime direction

Night keeps transport-specific work outside the routing and application pipeline:

```text
transport adapter -> Night Request -> app.handle(request) -> Night Response -> transport adapter
```

The standard ASGI callable remains the normal CPython adapter. Portable Web-standard adapters translate `Request` / `Response` data without duplicating routing, middleware, validation, error handling, HEAD/OPTIONS behavior, or session handling.

## Supported adapters

- **ASGI / CPython** — the default Night runtime.
- **Cloudflare Python Workers** — direct Workers Request/Response integration.
- **Browser Night** — Pyodide in the browser through `night_web`.
- **Node.js 22 / 24** — Pyodide hosted by Node through `night_node.mjs`; both lines run in CI.
- **Netlify Functions / Node 24** — Netlify's modern Web Request/Response API wraps the same Node adapter.
- **Vercel Python Functions** — direct ASGI hosting.

Node and Netlify intentionally share one adapter rather than maintaining platform-specific copies of Night's request pipeline.

## Runtime-dependent features

Runtime-dependent features remain explicit. File-system responses, native extensions such as `lupa`, SQLite-backed ORM behavior, WebSockets, and streaming may not be portable to every runtime even when the core request pipeline is. The current Node/Netlify Web bridge buffers HTTP bodies and uses Pyodide's virtual filesystem unless a host bridge is added.

This split lets Night add transports without turning `night.py` itself into a collection of platform SDK dependencies.
