# Request and response reference

## Request

`Request` is a slotted dataclass created for each request. It keeps raw ASGI scope access cheap while lazily decoding higher-level values.

Properties include:

- `method`, `path`, `query_string`, `query`
- `headers`, `cookies`
- `client`, `scheme`, `host`, `url`
- `state`, `path_params`
- `trace_id`, `span_id`

Awaitable methods:

```python
await req.body()
await req.text()
await req.json()
await req.form()
await req.files()
```

`header(name, default=None)` performs case-insensitive lookup without forcing construction of the full decoded header mapping. Once `req.headers` is requested, the complete mapping is cached.

`Request.body()` consumes ASGI `http.request` events and enforces the configured `max_body_size`. Higher-level body parsers reuse the cached body.

Trace helpers `trace_id`, `span_id`, and `trace_headers()` use or generate W3C-compatible trace values.

## Responses

Available response classes include:

- `Response`
- `JSONResponse`
- `PlainTextResponse`
- `HTMLResponse`
- `StreamingResponse`
- `FileResponse`

Helpers include `jsonify`, `text`, `html`, `redirect`, `stream`, `sse`, `send_file`, `query_result`, and `clear_client_storage`.

Returning a plain `dict` or `list` from a route produces JSON; `str` produces text; `bytes` produces a binary response; `None` produces an empty 204 response.

## JSON serializers

`JSONResponse` accepts an optional serializer:

```python
import orjson
from night import JSONResponse

response = JSONResponse({"ok": True}, dumps=orjson.dumps)
```

The default serializer is the standard library `json.dumps`. Alternate serializers may return either `str` or `bytes`.

## Headers

Night adds `Date` and `Content-Length` when appropriate. The HTTP Date value is cached at one-second precision to avoid formatting a new timestamp for every response.

Use `response.add_header()` when repeated headers are required. `Set-Cookie` values are preserved as separate raw headers.

## Cookies

```python
response.set_cookie(
    "session",
    value,
    httponly=True,
    secure=True,
    samesite="Lax",
)

response.delete_cookie("session")
```

## Streaming

`StreamingResponse` accepts a synchronous iterable or asynchronous iterable and emits chunks through ASGI response-body events. `sse()` formats items as Server-Sent Events.

Cloudflare's current `cloudflare_fetch()` bridge buffers the final Night response before creating the Workers Response; see the Cloudflare guide for current Edge-specific constraints.
