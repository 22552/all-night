# Application and routing reference

`Night` inherits `Router` and is both an ASGI application and the main configuration object.

## Construction

```python
app = Night(
    debug=False,
    max_body_size=16 * 1024 * 1024,
    secret_key=None,
)
```

The default request-body limit is 16 MiB. `secret_key` is only required for signed sessions, flash helpers, and CSRF features.

## Routing

| API | Purpose |
| --- | --- |
| `app.route(path, methods=..., name=..., body=...)` | Register a route. |
| `app.get/post/put/patch/delete/query/purge(...)` | Method-specific route decorators. |
| `app.mount(prefix, router)` | Mount a `Router` under a path. |
| `Blueprint(name, url_prefix=...)` | Named router; call `blueprint.register(app)`. |
| `app.url_for(name, **params)` | Build a named route URL. |
| `app.openapi()` | Return an OpenAPI 3.1 document as a dictionary. |
| `app.enable_csrf_endpoint(path="/csrf-token")` | Register the SPA token endpoint. |
| `app.static(...)` / `static(...)` | Serve static files through a router. |

Path converters are `str`, `int`, and `path`.

```python
@app.get("/users/<int:user_id>", name="user")
def get_user(user_id: int):
    return {"id": user_id}

url = app.url_for("user", user_id=42)
```

GET routes automatically support HEAD. OPTIONS responses are generated with an `Allow` header.

## Registration-time compilation

Night moves common routing work out of the request hot path. During route registration it:

- indexes static routes by method and path;
- recognizes common single-parameter dynamic routes;
- maintains prefix/terminal indexes for large dynamic route tables;
- classifies endpoint call shapes;
- compiles route-specific invokers for sync/async and direct-parameter cases.

Complex patterns fall back to the general regex router, preserving compatibility while keeping common REST route shapes cheap at request time.

`Route.body_model` records the dataclass supplied to `body=`. OpenAPI uses it to generate request-body schemas.

## Middleware and hooks

`app.use(middleware)` appends application middleware. Middleware receives `(req, call_next)` and returns a response.

Lifecycle hooks are registered with `before_request`, `after_request`, and `errorhandler`. Night skips empty middleware/hook paths so applications that do not use them do not pay the full middleware dispatch cost.

## JSON-RPC and Workers RPC

```python
@app.rpc("add")
def add(a: int, b: int):
    return a + b
```

The first RPC method installs Night's `/rpc` JSON-RPC endpoint. The same registry can be exposed inside Cloudflare Python Workers with:

```python
await app.cloudflare_rpc(method, args, kwargs)
```

The Workers bridge delegates Python/RPC value conversion to Cloudflare's `workers-runtime-sdk`.

## Cloudflare fetch bridge

Inside a Python Worker:

```python
return await app.cloudflare_fetch(request)
```

`cloudflare_fetch()` accepts the Workers Request wrapper, builds Night's HTTP request scope, invokes the normal application core, and returns a Workers Response. Cloudflare-specific imports remain optional for normal CPython deployments.
