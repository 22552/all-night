# Tooling, testing, and extensions

## Testing

```python
client = app.test_client()
response = client.get("/health")
assert response.status_code == 200
```

`TestClient` calls the ASGI application in-process and retains Cookies between requests.

## Middleware and hooks

Register application middleware with `app.use(middleware)`. A middleware receives `(req, call_next)` and returns a response. Built-ins are `logger_middleware`, `cors_middleware`, and `csrf_middleware`.

Use `before_request`, `after_request`, and `errorhandler` for request lifecycle customization.

## Extensions

`app.register_extension(extension)` accepts either an object implementing `init_app(app, **config)` or an app callable. `GraphQLExtension` requires the optional `graphql-core` package. JSON-RPC methods are registered with `@app.rpc("method")` and served at `/rpc`.


