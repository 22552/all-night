# Application and routing reference

`Night` inherits `Router`.

| API | Purpose |
| --- | --- |
| `Night(debug=False, max_body_size=..., secret_key=...)` | Create an ASGI application. |
| `app.route(path, methods=..., name=..., body=...)` | Register a route. |
| `app.get/post/put/patch/delete/query/purge(...)` | Method-specific route decorators. |
| `app.mount(prefix, router)` | Mount a `Router` under a path. |
| `Blueprint(name, url_prefix=...)` | Named router; call `blueprint.register(app)`. |
| `app.url_for(name, **params)` | Build a named route URL. |
| `app.openapi()` | Return an OpenAPI 3.1 document as a dictionary. |
| `app.enable_csrf_endpoint(path="/csrf-token")` | Register the SPA token endpoint. |
| `app.static(...)` / `static(...)` | Serve static files through a router. |

`Route.body_model` records the dataclass supplied to `body=`. OpenAPI uses it to generate a request-body schema.


