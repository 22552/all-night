# Application と Routing

| API | 用途 |
| --- | --- |
| `Night(...)` | ASGIアプリケーションを作成します。 |
| `app.route(...)` | メソッドとパスを指定してルートを登録します。 |
| `app.get/post/put/patch/delete/query/purge(...)` | HTTPメソッド別デコレータです。 |
| `app.mount(prefix, router)` | Routerを指定パス配下へマウントします。 |
| `Blueprint(name, url_prefix=...)` | 名前付きRouterです。`register(app)` で登録します。 |
| `app.url_for(name, **params)` | 名前付きルートのURLを生成します。 |
| `app.openapi()` | OpenAPI 3.1辞書を返します。 |
| `app.enable_csrf_endpoint()` | SPA向けCSRFトークンエンドポイントを登録します。 |

`body=Dataclass` で登録したルートは、OpenAPIのリクエストボディスキーマにも反映されます。


