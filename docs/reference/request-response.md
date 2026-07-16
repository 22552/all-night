# Request and response reference

## Request

`Request` exposes `method`, `path`, `query_string`, `query`, `headers`, `cookies`, `client`, `scheme`, `host`, `url`, `state`, and `path_params`.

Methods: `body()`, `text()`, `json()`, `form()`, and `files()` are awaitable. `header(name, default=None)` performs case-insensitive lookup.

Trace helpers: `trace_id`, `span_id`, and `trace_headers()` use or generate W3C-compatible trace values.

## Responses and helpers

`Response`, `JSONResponse`, `PlainTextResponse`, `HTMLResponse`, `StreamingResponse`, and `FileResponse` are available directly. Helpers include `jsonify`, `text`, `html`, `redirect`, `stream`, `sse`, `send_file`, `query_result`, and `clear_client_storage`.

For cookies, call `response.set_cookie(name, value, httponly=True, secure=True, samesite="Lax")` or `response.delete_cookie(name)`.


