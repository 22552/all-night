# CLI・テスト・拡張

```python
client = app.test_client()
response = client.get("/health")
assert response.status_code == 200
```

`TestClient` はASGIアプリをプロセス内で呼び出し、リクエスト間のCookieも保持します。

ミドルウェアは `app.use(middleware)` で登録します。組み込みは `logger_middleware`、`cors_middleware`、`csrf_middleware` です。リクエストフックには `before_request`、`after_request`、`errorhandler` を使います。

`app.register_extension()` は `init_app(app, **config)` を持つ拡張、またはアプリ用callableを登録します。JSON-RPCは `@app.rpc("method")` で登録し、`/rpc` に公開されます。


