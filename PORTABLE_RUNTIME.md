# Portable runtime direction

Night's HTTP core is a good candidate for runtimes beyond ASGI, including Pyodide-based edge environments.

The key architectural rule is to keep transport-specific work outside the routing and application pipeline:

```text
transport adapter -> Night Request -> app.handle(request) -> Night Response -> transport adapter
```

The existing ASGI callable can remain the default adapter. Future adapters can translate Web-standard `Request`/`Response` objects to Night's request/response types without duplicating routing, middleware, validation, error handling, HEAD/OPTIONS behavior, or session handling.

Runtime-dependent features should remain explicit. File-system responses, native extensions such as `lupa`, and SQLite-backed ORM behavior may not be portable to every edge runtime even when the core request pipeline is.

This document records the intended direction before a larger transport refactor lands.
