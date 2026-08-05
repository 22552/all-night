from __future__ import annotations

import typing as t
import urllib.parse

from night import Request, Response
from portable_runtime import handle


class _BodyReceiver:
    def __init__(self, body: bytes):
        self.body = body
        self.sent = False

    async def __call__(self):
        if self.sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        self.sent = True
        return {"type": "http.request", "body": self.body, "more_body": False}


async def request_from_web(request: t.Any, *, max_body_size: int) -> Request:
    parsed = urllib.parse.urlsplit(str(request.url))
    method = str(request.method).upper()

    headers: list[tuple[bytes, bytes]] = []
    try:
        iterator = request.headers.entries()
        for key, value in iterator:
            headers.append((str(key).lower().encode("latin-1"), str(value).encode("latin-1")))
    except Exception:
        for key, value in request.headers:
            headers.append((str(key).lower().encode("latin-1"), str(value).encode("latin-1")))

    body = b""
    if method not in {"GET", "HEAD"}:
        raw = await request.arrayBuffer()
        try:
            body = bytes(raw.to_py())
        except Exception:
            body = bytes(raw)

    if len(body) > max_body_size:
        from night import HTTPError

        raise HTTPError(413, "Request body too large")

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": parsed.scheme or "https",
        "path": parsed.path or "/",
        "raw_path": (parsed.path or "/").encode("utf-8"),
        "query_string": parsed.query.encode("latin-1"),
        "headers": headers,
        "server": (parsed.hostname or "edge", parsed.port),
        "client": None,
    }
    return Request(scope=scope, receive=_BodyReceiver(body), send=None, max_body_size=max_body_size)


def response_to_web(response: Response, *, response_class: t.Any) -> t.Any:
    body = getattr(response, "body", None)
    if not isinstance(body, (bytes, bytearray)):
        raise TypeError("Streaming responses require a Web ReadableStream adapter")

    headers: dict[str, str] = dict(response.headers)
    raw_headers = getattr(response, "raw_headers", ())
    if raw_headers:
        try:
            from js import Headers  # type: ignore

            web_headers = Headers.new()
            for key, value in headers.items():
                web_headers.set(key, value)
            for key, value in raw_headers:
                web_headers.append(str(key), str(value))
            headers_value: t.Any = web_headers
        except Exception:
            headers_value = headers
    else:
        headers_value = headers

    init = {"status": int(response.status), "headers": headers_value}
    return response_class.new(bytes(body), init)


async def fetch(app: t.Any, request: t.Any, *, response_class: t.Any) -> t.Any:
    req = await request_from_web(request, max_body_size=app.max_body_size)
    resp = await handle(app, req)
    return response_to_web(resp, response_class=response_class)


class CloudflareWorkerMixin:
    app: t.Any
    web_response_class: t.Any

    async def fetch(self, request):
        return await fetch(self.app, request, response_class=self.web_response_class)
