# Request / Response API

`Request` は `method`、`path`、`query`、`headers`、`cookies`、`client`、`url`、`state`、`path_params` を公開します。

`body()`、`text()`、`json()`、`form()`、`files()` はawait可能です。`trace_id`、`span_id`、`trace_headers()` はトレース伝搬を支援します。

主なレスポンス型は `Response`、`JSONResponse`、`PlainTextResponse`、`HTMLResponse`、`StreamingResponse`、`FileResponse` です。Cookieは `response.set_cookie()` と `response.delete_cookie()` で設定します。


