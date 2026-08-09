# CLI・テスト・拡張

```python
client = app.test_client()
response = client.get("/health")
assert response.status_code == 200
```

`TestClient` はASGIアプリをプロセス内で呼び出し、リクエスト間のCookieも保持します。

ミドルウェアは `app.use(middleware)` で登録します。組み込みは `logger_middleware`、`cors_middleware`、`csrf_middleware` です。リクエストフックには `before_request`、`after_request`、`errorhandler` を使います。

`app.register_extension()` は `init_app(app, **config)` を持つ拡張、またはアプリ用callableを登録します。JSON-RPCは `@app.rpc("method")` で登録し、`/rpc` に公開されます。

### Fast mode時のサーバー選択

読み込んだアプリで `app.fast()` が有効な場合、`night run` は `all-night[standard]` によって利用可能な `uvloop`、`httptools`、`websockets` をUvicornへ指定します。fast modeでなければ従来のUvicornデフォルトを維持します。
