# Tooling, testing, RPC, and extensions

## CLI

Installing `all-night` exposes the `night` command:

```bash
night run app.py
night routes app.py
night shell app.py
```

`night run` starts the selected application through the CLI's ASGI-server integration. You can also run the app directly with Uvicorn, Hypercorn, or another ASGI server.

## Testing

```python
with app.test_client() as client:
    response = client.get("/health")
    assert response.status_code == 200
```

`TestClient` calls Night in-process, retains Cookies between requests, and reuses an `asyncio.Runner` instead of creating a new event loop for every request.

Call `client.close()` when not using it as a context manager. A closed client can lazily create a new Runner on the next request.

`TestResponse` exposes:

- `status_code`
- `headers`
- `data`
- `text`
- `get_json()`

Cross-framework TestClient benchmarks are intentionally labeled as rough comparisons because each framework's client performs different bookkeeping. Use a real HTTP server benchmark before making production throughput claims.

## Middleware and hooks

Register application middleware with `app.use(middleware)`. A middleware receives `(req, call_next)` and returns a response.

Built-ins include `logger_middleware`, `cors_middleware`, and `csrf_middleware`.

Use `before_request`, `after_request`, and `errorhandler` for lifecycle customization. Night has fast paths for applications with no middleware or hooks.

## Extensions

`app.register_extension(extension)` accepts either an object implementing `init_app(app, **config)` or an app callable.

`GraphQLExtension` requires the optional `graphql-core` package. Lua-backed features require the optional Lua integration used by the application.

## JSON-RPC

Register methods with:

```python
@app.rpc("add")
def add(a, b):
    return a + b
```

Night installs `/rpc` as a JSON-RPC 2.0 POST endpoint when the first method is registered.

## Cloudflare Workers RPC

Inside Cloudflare Python Workers, the same registry can be exposed through Service Bindings:

```python
class Default(WorkerEntrypoint):
    async def night_rpc(self, method, args=None, kwargs=None):
        return await app.cloudflare_rpc(method, args, kwargs)
```

The bridge uses `workers.rpc.python_from_rpc()` and `python_to_rpc()` from `workers-runtime-sdk`. Keep Workers-specific code in the Worker entrypoint so normal Night applications remain dependency-free.

## Benchmarks

`benchmarks/fast_path.py` contains development benchmarks for:

- Night internal route hot paths;
- static routes;
- one dynamic route;
- large dynamic route tables;
- rough in-process comparisons against other Python web frameworks when their optional benchmark dependencies are installed.

When changing routing, dispatch, Request/Response construction, or TestClient internals, run both the full test suite and the benchmark before merging. Prefer same-runner A/B comparisons over comparing absolute timings from different machines.
