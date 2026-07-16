# Night documentation

Night is a single-file ASGI framework. This documentation follows the public API implemented in `night.py`.

日本語版は [日本語ドキュメント](ja/README.md) を参照してください。

## Start here

- [Quickstart](getting-started/quickstart.md) — install, run, and write a first application
- [HTTP applications](guides/http.md) — routing, requests, responses, forms, files, and validation
- [Security](guides/security.md) — sessions, cookies, CSRF, and trusted Lua macros
- [Realtime](guides/realtime.md) — SSE, WebSocket, lifespan, and streaming

## Reference

- [Application and routing](reference/application.md)
- [Request and response API](reference/request-response.md)
- [SQLite ORM](reference/orm.md)
- [CLI, testing, and extensions](reference/tooling.md)
- [Deployment notes](operations/deployment.md)

## Design boundaries

Night deliberately keeps its core dependency-free. Optional integrations such as `uvicorn`, `graphql-core`, and `lupa` are installed by the application that uses them.

