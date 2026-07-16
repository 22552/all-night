#!/usr/bin/env python3
"""night.py - a tiny, single-file Flask-like ASGI web framework.

This module intentionally evolves over time.

Goals
- Single file.
- Flask-ish decorator routing.
- ASGI 3.0 app callable.
- Minimal but practical: request/response, query, path params, JSON, middleware.

This revision adds:
- Query params parsing and cookie parsing.
- URL generation (url_for) and named routes.
- Before/after request hooks.
- Error handlers (@app.errorhandler).
- Streaming responses.
- Static files helper with safe path join.
- Blueprint-like router mounting via app.mount(prefix, router).
- Request.state (dict-like) and app.state for shared state.
- Request.client, Request.url, and robust header access.
- 304 / ETag / If-Modified-Since for FileResponse.
- HEAD support (auto) and OPTIONS auto-response.

Dependencies: none (optional uvicorn for running).
"""

from __future__ import annotations

import asyncio
import contextvars
import dataclasses
import datetime as _dt
import email.utils
import hashlib
import inspect
import json
import mimetypes
import os
import re
import sys
import traceback
import typing as t
import urllib.parse
import argparse
import runpy

# ----------------------------
# Utilities
# ----------------------------

_T = t.TypeVar("_T")
MAX_BODY_SIZE = 16 * 1024 * 1024


class LuaUnavailable(RuntimeError):
    """Raised when Lua macros are used without the optional lupa package."""


def _lua_macro_endpoint(source: str) -> t.Callable:
    """Build an endpoint from a small, sandboxed Lua function.

    The script must return a string, number, or a table containing ``body``,
    ``status``, and optional ``headers``.  Lua macros are deliberately
    optional: applications that do not use them keep zero dependencies.
    """
    try:
        from lupa import LuaRuntime
    except ImportError as exc:
        raise LuaUnavailable("Lua macros require the optional 'lupa' package") from exc

    lua = LuaRuntime(unpack_returned_tuples=True)
    # Remove libraries that provide filesystem, process, module-loading, or
    # debug access.  The macro still has basic Lua values and functions.
    lua.execute("os=nil; io=nil; debug=nil; package=nil; require=nil; dofile=nil; loadfile=nil")
    fn = lua.execute(
        "local f = function(req) " + source + " end; return f"
    )

    async def endpoint(req: Request, **params):
        data = {
            "method": req.method,
            "path": req.path,
            "query": req.query,
            "headers": req.headers,
            "cookies": req.cookies,
            "params": params,
        }
        result = fn(data)
        if isinstance(result, str):
            return PlainTextResponse(result)
        if isinstance(result, (int, float)):
            return PlainTextResponse(str(result))
        if result is None:
            return Response(b"", status=204)
        body = result["body"]
        status = int(result["status"] or 200)
        headers = dict(result["headers"] or {})
        return Response(_to_bytes(str(body)), status=status, headers=headers)

    return endpoint


def _to_bytes(x: t.Union[str, bytes, bytearray]) -> bytes:
    if isinstance(x, (bytes, bytearray)):
        return bytes(x)
    return x.encode("utf-8")


def _guess_content_type(path: str, default: str = "application/octet-stream") -> str:
    ctype, _ = mimetypes.guess_type(path)
    return ctype or default


def _http_date(dt: _dt.datetime | None = None) -> str:
    if dt is None:
        dt = _dt.datetime.now(tz=_dt.timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return email.utils.format_datetime(dt, usegmt=True)


def _parse_http_date(s: str) -> _dt.datetime | None:
    try:
        dt = email.utils.parsedate_to_datetime(s)
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_dt.timezone.utc)
        return dt
    except Exception:
        return None


def _parse_query(qs: bytes) -> dict[str, t.Union[str, list[str]]]:
    # Keep a Flask-ish shape: key -> str or list[str]
    if not qs:
        return {}
    parsed = urllib.parse.parse_qs(qs.decode("latin-1"), keep_blank_values=True)
    out: dict[str, t.Union[str, list[str]]] = {}
    for k, vals in parsed.items():
        if len(vals) == 1:
            out[k] = vals[0]
        else:
            out[k] = vals
    return out


def _parse_cookies(cookie_header: str | None) -> dict[str, str]:
    """Parse Cookie header into a dict.

    This is intentionally small (not a full RFC6265 implementation) but it:
    - strips whitespace
    - ignores empty keys
    - unquotes simple quoted values
    - percent-decodes values (common in practice)

    Note: if a cookie name appears multiple times, the last one wins.
    """

    if not cookie_header:
        return {}

    cookies: dict[str, str] = {}

    for part in cookie_header.split(";"):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        k = k.strip()
        v = v.strip()
        if not k:
            continue

        # Unquote "..." values.
        if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
            v = v[1:-1]

        # Percent-decoding is common for cookie values.
        try:
            v = urllib.parse.unquote(v)
        except Exception:
            pass

        cookies[k] = v

    return cookies


def _safe_join(root: str, path: str) -> str:
    # Prevent path traversal; returns a normalized absolute path under root.
    root_abs = os.path.abspath(root)
    target = os.path.abspath(os.path.join(root_abs, path.lstrip("/")))
    if os.path.commonpath([root_abs, target]) != root_abs:
        raise HTTPError(403, "Forbidden")
    return target


# ----------------------------
# Exceptions
# ----------------------------


class HTTPError(Exception):
    def __init__(self, status: int, detail: str = ""):
        self.status = int(status)
        self.detail = detail
        super().__init__(f"HTTP {status}: {detail}")


class NotFound(HTTPError):
    def __init__(self, detail: str = "Not Found"):
        super().__init__(404, detail)


class MethodNotAllowed(HTTPError):
    def __init__(self, allowed: t.Iterable[str] = (), detail: str = "Method Not Allowed"):
        self.allowed = sorted(set(allowed))
        super().__init__(405, detail)


# ----------------------------
# Request / Response
# ----------------------------


@dataclasses.dataclass
class Request:
    scope: dict
    receive: t.Callable
    send: t.Callable

    _body: bytes | None = None
    _json: t.Any = dataclasses.field(default=None, init=False)
    _json_loaded: bool = dataclasses.field(default=False, init=False)
    _query: dict[str, t.Union[str, list[str]]] | None = dataclasses.field(default=None, init=False)
    _cookies: dict[str, str] | None = dataclasses.field(default=None, init=False)
    path_params: dict[str, t.Any] = dataclasses.field(default_factory=dict)
    max_body_size: int = MAX_BODY_SIZE
    _headers: dict[str, str] | None = dataclasses.field(default=None, init=False)

    @property
    def method(self) -> str:
        return (self.scope.get("method") or "GET").upper()

    @property
    def path(self) -> str:
        return self.scope.get("path") or "/"

    @property
    def query_string(self) -> bytes:
        return self.scope.get("query_string") or b""

    @property
    def query(self) -> dict[str, t.Union[str, list[str]]]:
        if self._query is None:
            self._query = _parse_query(self.query_string)
        return self._query

    @property
    def headers(self) -> dict[str, str]:
        if self._headers is not None:
            return self._headers
        # ASGI provides list[(bytes, bytes)]
        hs = {}
        for k, v in self.scope.get("headers") or []:
            hs[k.decode("latin-1").lower()] = v.decode("latin-1")
        self._headers = hs
        return hs

    def header(self, name: str, default: str | None = None) -> str | None:
        return self.headers.get(name.lower(), default)

    @property
    def cookies(self) -> dict[str, str]:
        if self._cookies is None:
            self._cookies = _parse_cookies(self.header("cookie"))
        return self._cookies

    @property
    def client(self) -> tuple[str, int] | None:
        c = self.scope.get("client")
        if not c:
            return None
        try:
            host, port = c
            return str(host), int(port)
        except Exception:
            return None

    @property
    def scheme(self) -> str:
        return self.scope.get("scheme") or "http"

    @property
    def host(self) -> str | None:
        # Prefer Host header
        h = self.header("host")
        if h:
            return h
        c = self.client
        if c:
            return c[0]
        return None

    @property
    def url(self) -> str:
        host = self.host or ""
        qs = self.query_string.decode("latin-1") if self.query_string else ""
        base = f"{self.scheme}://{host}{self.path}" if host else self.path
        return base + ("?" + qs if qs else "")

    @property
    def state(self) -> dict:
        self.scope.setdefault("state", {})
        st = self.scope["state"]
        if not isinstance(st, dict):
            # Keep it simple: enforce dict.
            self.scope["state"] = {}
        return self.scope["state"]

    async def body(self) -> bytes:
        if self._body is not None:
            return self._body
        body = bytearray()
        content_length = self.header("content-length")
        if content_length and content_length.isdigit() and int(content_length) > self.max_body_size:
            raise HTTPError(413, "Request body too large")
        more = True
        while more:
            event = await self.receive()
            if event["type"] != "http.request":
                continue
            body += event.get("body", b"")
            if len(body) > self.max_body_size:
                raise HTTPError(413, "Request body too large")
            more = event.get("more_body", False)
        self._body = bytes(body)
        return self._body

    async def text(self, encoding: str = "utf-8") -> str:
        return (await self.body()).decode(encoding, errors="replace")

    async def json(self) -> t.Any:
        if self._json_loaded:
            return self._json
        b = await self.body()
        if not b:
            self._json = None
        else:
            self._json = json.loads(b.decode("utf-8"))
        self._json_loaded = True
        return self._json

    async def form(self) -> "QueryDict":
        body = await self.body()
        ctype = (self.header("content-type") or "").split(";", 1)[0].strip().lower()
        if ctype == "application/x-www-form-urlencoded":
            return QueryDict(urllib.parse.parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True))
        if ctype == "multipart/form-data":
            raise NotImplementedError("multipart form parsing is not implemented yet")
        return QueryDict()


class QueryDict(dict[str, list[str]]):
    """Django-like multi-value query/form mapping."""

    def __init__(self, values: t.Mapping[str, t.Any] | None = None):
        super().__init__({k: list(v) if isinstance(v, list) else [str(v)] for k, v in (values or {}).items()})

    def get(self, key: str, default: t.Any = None):
        values = super().get(key)
        return values[-1] if values else default

    def getlist(self, key: str) -> list[str]:
        return list(super().get(key, []))


class WebSocket:
    def __init__(self, scope: dict, receive, send):
        self.scope = scope
        self.receive = receive
        self.send = send

    @property
    def path(self) -> str:
        return self.scope.get("path") or "/"

    async def accept(self, subprotocol: str | None = None):
        event = {"type": "websocket.accept"}
        if subprotocol:
            event["subprotocol"] = subprotocol
        await self.send(event)

    async def receive_text(self) -> str:
        event = await self.receive()
        if event["type"] == "websocket.disconnect":
            raise ConnectionError("WebSocket disconnected")
        if event.get("text") is not None:
            return event["text"]
        return (event.get("bytes") or b"").decode("utf-8", errors="replace")

    async def send_text(self, data: str):
        await self.send({"type": "websocket.send", "text": str(data)})

    async def send_bytes(self, data: bytes):
        await self.send({"type": "websocket.send", "bytes": bytes(data)})

    async def close(self, code: int = 1000, reason: str = ""):
        event = {"type": "websocket.close", "code": int(code)}
        if reason:
            event["reason"] = reason
        await self.send(event)


class Response:
    def __init__(
        self,
        body: t.Union[str, bytes, bytearray] = b"",
        status: int = 200,
        headers: t.Mapping[str, str] | None = None,
        content_type: str | None = None,
        raw_headers: t.Iterable[tuple[str, str]] | None = None,
    ):
        self.status = int(status)
        self.body = _to_bytes(body)
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        self.raw_headers = list(raw_headers or ())
        if content_type is not None:
            self.headers["content-type"] = content_type
        if "date" not in self.headers:
            self.headers["date"] = _http_date()
        if "content-length" not in self.headers:
            self.headers["content-length"] = str(len(self.body))

    def asgi_headers(self) -> list[tuple[bytes, bytes]]:
        normal = [(k, v) for k, v in self.headers.items() if k != "set-cookie"]
        return [(k.encode("latin-1"), v.encode("latin-1")) for k, v in normal + self.raw_headers]

    def add_header(self, name: str, value: str):
        self.raw_headers.append((name.lower(), value))

    async def __call__(self, scope, receive, send):
        await send({"type": "http.response.start", "status": self.status, "headers": self.asgi_headers()})
        await send({"type": "http.response.body", "body": self.body, "more_body": False})


class StreamingResponse(Response):
    """Send an async iterator/generator as chunked body.

    Note: Many servers will handle this fine. We do not set Content-Length.
    """

    def __init__(
        self,
        body_iter: t.AsyncIterable[t.Union[str, bytes, bytearray]] | t.Iterable[t.Union[str, bytes, bytearray]],
        status: int = 200,
        headers: t.Mapping[str, str] | None = None,
        content_type: str | None = "application/octet-stream",
    ):
        self.status = int(status)
        self._body_iter = body_iter
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        if content_type is not None:
            self.headers.setdefault("content-type", content_type)
        if "date" not in self.headers:
            self.headers["date"] = _http_date()
        # Intentionally omit content-length
        self.body = b""  # compatibility

    async def __call__(self, scope, receive, send):
        await send({"type": "http.response.start", "status": self.status, "headers": self.asgi_headers()})

        it = self._body_iter
        if hasattr(it, "__aiter__"):
            async for chunk in t.cast(t.AsyncIterable, it):
                await send({"type": "http.response.body", "body": _to_bytes(chunk), "more_body": True})
        else:
            for chunk in t.cast(t.Iterable, it):
                await send({"type": "http.response.body", "body": _to_bytes(chunk), "more_body": True})

        await send({"type": "http.response.body", "body": b"", "more_body": False})


def sse(
    body_iter: t.AsyncIterable[t.Any] | t.Iterable[t.Any],
    *,
    status: int = 200,
    headers: t.Mapping[str, str] | None = None,
) -> StreamingResponse:
    """Create a Server-Sent Events response.

    Items may be strings or dictionaries with ``data``, ``event``, ``id``,
    and ``retry`` keys.  A blank line terminates each event.
    """
    async def encode_async():
        async for item in t.cast(t.AsyncIterable, body_iter):
            yield _format_sse(item)

    def encode_sync():
        for item in t.cast(t.Iterable, body_iter):
            yield _format_sse(item)

    source = encode_async() if hasattr(body_iter, "__aiter__") else encode_sync()
    h = dict(headers or {})
    h.setdefault("cache-control", "no-cache")
    h.setdefault("connection", "keep-alive")
    return StreamingResponse(source, status=status, headers=h, content_type="text/event-stream")


def _format_sse(item: t.Any) -> str:
    if not isinstance(item, dict):
        item = {"data": item}
    lines: list[str] = []
    for key in ("id", "event", "retry"):
        if item.get(key) is not None:
            lines.append(f"{key}: {item[key]}")
    data = str(item.get("data", ""))
    lines.extend(f"data: {line}" for line in data.splitlines() or [""])
    return "\n".join(lines) + "\n\n"


class JSONResponse(Response):
    def __init__(
        self,
        data: t.Any,
        status: int = 200,
        headers: t.Mapping[str, str] | None = None,
        *,
        dumps: t.Callable[..., str] = json.dumps,
    ):
        """JSON response helper.

        `dumps` can be overridden to plug in a faster JSON library (e.g. orjson)
        while keeping night single-file.
        """

        body = dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        h = dict(headers or {})
        h.setdefault("content-type", "application/json; charset=utf-8")
        super().__init__(body=body, status=status, headers=h)


class PlainTextResponse(Response):
    def __init__(self, text: str, status: int = 200, headers: t.Mapping[str, str] | None = None):
        h = dict(headers or {})
        h.setdefault("content-type", "text/plain; charset=utf-8")
        super().__init__(body=text, status=status, headers=h)


class HTMLResponse(Response):
    def __init__(self, html: str, status: int = 200, headers: t.Mapping[str, str] | None = None):
        h = dict(headers or {})
        h.setdefault("content-type", "text/html; charset=utf-8")
        super().__init__(body=html, status=status, headers=h)


class FileResponse(Response):
    def __init__(
        self,
        path: str,
        req: Request | None = None,
        status: int = 200,
        headers: t.Mapping[str, str] | None = None,
        download_name: str | None = None,
        cache_seconds: int | None = 3600,
    ):
        # Conditional GET support: ETag + If-None-Match, and If-Modified-Since.
        st = os.stat(path)
        mtime = _dt.datetime.fromtimestamp(st.st_mtime, tz=_dt.timezone.utc)

        etag = 'W/"%s"' % hashlib.sha256(
            (str(st.st_size) + ":" + str(int(st.st_mtime))).encode("utf-8")
        ).hexdigest()[:16]

        h = dict(headers or {})
        h.setdefault("content-type", _guess_content_type(path))
        h.setdefault("etag", etag)
        h.setdefault("last-modified", _http_date(mtime))
        if download_name:
            h.setdefault("content-disposition", f'attachment; filename="{download_name}"')
        if cache_seconds is not None:
            h.setdefault("cache-control", f"public, max-age={int(cache_seconds)}")

        if req is not None:
            inm = req.header("if-none-match")
            if inm and inm.strip() == etag:
                super().__init__(body=b"", status=304, headers=h)
                # Remove content-length for 304
                self.headers.pop("content-length", None)
                return

            ims = req.header("if-modified-since")
            if ims:
                dt = _parse_http_date(ims)
                if dt is not None:
                    # RFC: if resource not modified since ims -> 304
                    if mtime.replace(microsecond=0) <= dt.astimezone(_dt.timezone.utc).replace(microsecond=0):
                        super().__init__(body=b"", status=304, headers=h)
                        self.headers.pop("content-length", None)
                        return

        with open(path, "rb") as f:
            data = f.read()
        super().__init__(body=data, status=status, headers=h)


# ----------------------------
# Routing
# ----------------------------


_converter_patterns = {
    "str": r"[^/]+",
    "int": r"\d+",
    "path": r".+",
}


@dataclasses.dataclass
class Route:
    methods: set[str]
    pattern: re.Pattern
    param_names: list[str]
    endpoint: t.Callable
    raw_path: str
    name: str | None = None


def compile_path(path: str) -> tuple[re.Pattern, list[str]]:
    # /users/<int:id>/posts/<slug>
    # converters: str (default), int, path
    param_names: list[str] = []

    def repl(m: re.Match) -> str:
        inner = m.group(1)
        if ":" in inner:
            conv, name = inner.split(":", 1)
        else:
            conv, name = "str", inner
        if conv not in _converter_patterns:
            conv = "str"
        param_names.append(name)
        return f"(?P<{name}>{_converter_patterns[conv]})"

    regex = re.sub(r"<([^>]+)>", repl, path)
    regex = "^" + regex.rstrip("/") + "/?$"
    return re.compile(regex), param_names


def _format_path(path_template: str, params: dict[str, t.Any]) -> str:
    # Replace <name> or <conv:name> segments.
    def repl(m: re.Match) -> str:
        inner = m.group(1)
        name = inner.split(":", 1)[1] if ":" in inner else inner
        if name not in params:
            raise KeyError(name)
        return urllib.parse.quote(str(params[name]), safe="")

    return re.sub(r"<([^>]+)>", repl, path_template)


# ----------------------------
# App / middleware
# ----------------------------


_current_request: contextvars.ContextVar[Request | None] = contextvars.ContextVar("night_request", default=None)


def request() -> Request:
    r = _current_request.get()
    if r is None:
        raise RuntimeError("No active request in context")
    return r


Middleware = t.Callable[[Request, t.Callable[[], t.Awaitable[Response]]], t.Awaitable[Response]]
BeforeHook = t.Callable[[Request], t.Awaitable[t.Optional[Response]] | t.Optional[Response]]
AfterHook = t.Callable[[Request, Response], t.Awaitable[Response] | Response]
ErrorHandler = t.Callable[[Request, Exception], t.Awaitable[Response] | Response]


class Extension:
    """Base class for reusable Night extensions.

    Subclasses typically register routes, middleware, or hooks in
    ``init_app``.  Extensions should keep their own configuration in the
    instance rather than mutating global state.
    """

    def init_app(self, app: "Night", **config: t.Any) -> None:
        raise NotImplementedError


class GraphQLExtension(Extension):
    """Optional GraphQL-over-HTTP endpoint powered by ``graphql-core``."""

    name = "graphql"

    def __init__(self, schema: t.Any, *, path: str = "/graphql"):
        self.schema = schema
        self.path = path

    def init_app(self, app: "Night", **config: t.Any) -> None:
        try:
            from graphql import graphql
        except ImportError as exc:
            raise RuntimeError("GraphQLExtension requires: pip install graphql-core") from exc

        async def endpoint(req: Request):
            payload = await req.json() if req.method in {"POST", "QUERY"} else None
            if payload is None:
                query = req.query.get("query", "")
                variables = req.query.get("variables")
                operation_name = req.query.get("operationName")
                if isinstance(variables, str) and variables:
                    try:
                        variables = json.loads(variables)
                    except json.JSONDecodeError:
                        return JSONResponse({"errors": [{"message": "Invalid variables JSON"}]}, status=400)
            else:
                if not isinstance(payload, dict):
                    return JSONResponse({"errors": [{"message": "Request must be a JSON object"}]}, status=400)
                query = payload.get("query", "")
                variables = payload.get("variables")
                operation_name = payload.get("operationName")

            if not isinstance(query, str) or not query.strip():
                return JSONResponse({"errors": [{"message": "Missing GraphQL query"}]}, status=400)
            result = graphql(
                self.schema,
                query,
                variable_values=variables,
                operation_name=operation_name,
            )
            if inspect.isawaitable(result):
                result = await t.cast(t.Awaitable, result)
            output: dict[str, t.Any] = {}
            if result.data is not None:
                output["data"] = result.data
            if result.errors:
                output["errors"] = [{"message": str(error)} for error in result.errors]
            return JSONResponse(output, status=200 if not result.errors else 400)

        app.route(self.path, methods=("GET", "POST", "QUERY"), name="graphql")(endpoint)


class Router:
    """A blueprint-like container for routes."""

    def __init__(self):
        self.routes: list[Route] = []

    def route(self, path: str, methods: t.Iterable[str] = ("GET",), *, name: str | None = None):
        methods_set = {m.upper() for m in methods}

        def decorator(fn: t.Callable):
            pattern, names = compile_path(path)
            self.routes.append(
                Route(methods=methods_set, pattern=pattern, param_names=names, endpoint=fn, raw_path=path, name=name)
            )
            return fn

        return decorator

    def get(self, path: str, *, name: str | None = None):
        return self.route(path, methods=("GET",), name=name)

    def post(self, path: str, *, name: str | None = None):
        return self.route(path, methods=("POST",), name=name)

    def put(self, path: str, *, name: str | None = None):
        return self.route(path, methods=("PUT",), name=name)

    def delete(self, path: str, *, name: str | None = None):
        return self.route(path, methods=("DELETE",), name=name)

    def query(self, path: str, *, name: str | None = None):
        return self.route(path, methods=("QUERY",), name=name)

    def patch(self, path: str, *, name: str | None = None):
        return self.route(path, methods=("PATCH",), name=name)


class Blueprint(Router):
    """A named, mountable collection of routes and optional setup hook."""

    def __init__(self, name: str, *, url_prefix: str = "", setup: t.Callable | None = None):
        super().__init__()
        self.name = name
        self.url_prefix = ("/" + url_prefix.strip("/")) if url_prefix else ""
        self.setup = setup

    def register(self, app: "Night", *, url_prefix: str | None = None):
        prefix = self.url_prefix if url_prefix is None else url_prefix
        if self.setup is not None:
            self.setup(self)
            self.setup = None
        app.mount(prefix, self)
        return self


class Night(Router):
    def __init__(self, *, debug: bool = False, max_body_size: int = MAX_BODY_SIZE):
        super().__init__()
        self.debug = bool(debug)
        self.max_body_size = int(max_body_size)
        self.middlewares: list[Middleware] = []
        self.before_hooks: list[BeforeHook] = []
        self.after_hooks: list[AfterHook] = []
        self.error_handlers: dict[type[BaseException], ErrorHandler] = {}
        self.state: dict[str, t.Any] = {}
        self.extensions: dict[str, t.Any] = {}
        self.websocket_routes: list[Route] = []
        self.startup_hooks: list[t.Callable] = []
        self.shutdown_hooks: list[t.Callable] = []

    def on_startup(self, fn: t.Callable):
        self.startup_hooks.append(fn)
        return fn

    def on_shutdown(self, fn: t.Callable):
        self.shutdown_hooks.append(fn)
        return fn

    def register_extension(
        self,
        extension: t.Any,
        *,
        name: str | None = None,
        **config: t.Any,
    ) -> t.Any:
        """Install an extension and return it.

        An extension may be an object with ``init_app(app, **config)`` or a
        callable accepting the app.  The optional name is used for lookup in
        ``app.extensions`` and defaults to the class name.
        """
        key = name or getattr(extension, "name", None) or extension.__class__.__name__.lower()
        if hasattr(extension, "init_app"):
            extension.init_app(self, **config)
        elif callable(extension):
            result = extension(self, **config)
            if result is not None:
                extension = result
        else:
            raise TypeError("extension must be callable or define init_app(app, **config)")
        self.extensions[key] = extension
        return extension

    def register_blueprint(self, blueprint: Blueprint, *, url_prefix: str | None = None):
        """Mount a Blueprint and return it for fluent setup code."""
        return blueprint.register(self, url_prefix=url_prefix)

    def websocket(self, path: str, *, name: str | None = None):
        def decorator(fn: t.Callable):
            pattern, names = compile_path(path)
            self.websocket_routes.append(Route({"WEBSOCKET"}, pattern, names, fn, path, name))
            return fn
        return decorator

    async def _handle_websocket(self, scope, receive, send):
        path = scope.get("path") or "/"
        for route in self.websocket_routes:
            match = route.pattern.match(path)
            if not match:
                continue
            ws = WebSocket(scope, receive, send)
            try:
                params = match.groupdict()
                sig = inspect.signature(route.endpoint)
                kwargs = dict(params)
                if "ws" in sig.parameters:
                    result = route.endpoint(ws=ws, **kwargs)
                elif sig.parameters:
                    result = route.endpoint(ws, **kwargs)
                else:
                    result = route.endpoint(**kwargs)
                if inspect.isawaitable(result):
                    await t.cast(t.Awaitable, result)
            except ConnectionError:
                return
            except Exception:
                await ws.close(code=1011, reason="Internal server error")
            return
        await send({"type": "websocket.close", "code": 1008})

    def lua_macro(
        self,
        path: str,
        source: str,
        *,
        methods: t.Iterable[str] = ("GET",),
        name: str | None = None,
    ):
        """Register a small optional Lua macro as a normal route.

        Example::

            app.lua_macro("/hello", 'return "hello " .. req.query.name')

        Install ``lupa`` separately when Lua support is wanted.  The macro
        receives only a plain request-data table and cannot access the Python
        process through this API.
        """
        return self.route(path, methods=methods, name=name)(_lua_macro_endpoint(source))

    # ---- middleware API ----
    def use(self, middleware: Middleware):
        self.middlewares.append(middleware)
        return middleware

    # ---- hooks ----
    def before_request(self, fn: BeforeHook):
        self.before_hooks.append(fn)
        return fn

    def after_request(self, fn: AfterHook):
        self.after_hooks.append(fn)
        return fn

    def errorhandler(self, exc_type: type[BaseException]):
        def decorator(fn: ErrorHandler):
            self.error_handlers[exc_type] = fn
            return fn

        return decorator

    # ---- mounting ----
    def mount(self, prefix: str, router: Router):
        prefix = ("/" + prefix.strip("/")) if prefix else ""
        for r in router.routes:
            mounted_path = prefix + ("/" + r.raw_path.lstrip("/"))
            pattern, names = compile_path(mounted_path)
            self.routes.append(
                Route(
                    methods=set(r.methods),
                    pattern=pattern,
                    param_names=names,
                    endpoint=r.endpoint,
                    raw_path=mounted_path,
                    name=r.name,
                )
            )
        return router

    # ---- url building ----
    def url_for(self, name: str, /, **params: t.Any) -> str:
        for r in self.routes:
            if r.name == name:
                path = _format_path(r.raw_path, params)
                # remaining params become query params
                used = set(r.param_names)
                q = {k: v for k, v in params.items() if k not in used}
                if q:
                    return path + "?" + urllib.parse.urlencode(q, doseq=True)
                return path
        raise KeyError(f"No route with name={name!r}")

    # ---- dispatch ----
    def _match(self, path: str) -> tuple[Route, dict[str, str]]:
        for r in self.routes:
            m = r.pattern.match(path)
            if m:
                return r, m.groupdict()
        raise NotFound()

    def _match_method(self, path: str, method: str) -> tuple[Route, dict[str, str]]:
        path_matched = False
        for route in self.routes:
            match = route.pattern.match(path)
            if not match:
                continue
            path_matched = True
            if method in route.methods:
                return route, match.groupdict()
        if path_matched:
            raise MethodNotAllowed(self._allowed_methods_for_path(path))
        raise NotFound()

    async def _call_endpoint(self, fn: t.Callable, req: Request, params: dict[str, str]) -> Response:
        # Convert params types based on annotations where possible
        try:
            sig = inspect.signature(fn)
        except Exception:
            sig = None

        kwargs: dict[str, t.Any] = dict(params)
        if sig is not None:
            for name, p in sig.parameters.items():
                if name in kwargs and p.annotation is int:
                    try:
                        kwargs[name] = int(kwargs[name])
                    except Exception:
                        pass

        # Common patterns: fn(req, **params) or fn(**params) or fn(req)
        try:
            if sig is not None and "req" in sig.parameters:
                res = fn(req=req, **kwargs)
            else:
                if sig is not None and len(sig.parameters) >= 1:
                    first = next(iter(sig.parameters.values()))
                    if first.annotation is Request or first.name in ("request", "req"):
                        res = fn(req, **kwargs)
                    else:
                        res = fn(**kwargs)
                else:
                    res = fn(**kwargs)

            if inspect.isawaitable(res):
                res = await t.cast(t.Awaitable, res)

            if isinstance(res, Response):
                return res
            if isinstance(res, (dict, list)):
                return JSONResponse(res)
            if isinstance(res, (str, bytes, bytearray)):
                if isinstance(res, str):
                    return PlainTextResponse(res)
                return Response(res)
            if res is None:
                return Response(b"", status=204)
            return PlainTextResponse(str(res))
        except HTTPError:
            raise
        except Exception:
            if self.debug:
                tb = traceback.format_exc()
                return PlainTextResponse(tb, status=500)
            return PlainTextResponse("Internal Server Error", status=500)

    async def _run_before_hooks(self, req: Request) -> Response | None:
        for fn in self.before_hooks:
            res = fn(req)
            if inspect.isawaitable(res):
                res = await t.cast(t.Awaitable, res)
            if isinstance(res, Response):
                return res
        return None

    async def _run_after_hooks(self, req: Request, resp: Response) -> Response:
        for fn in self.after_hooks:
            out = fn(req, resp)
            if inspect.isawaitable(out):
                out = await t.cast(t.Awaitable, out)
            if isinstance(out, Response):
                resp = out
        return resp

    def _find_error_handler(self, exc: BaseException) -> ErrorHandler | None:
        # Exact match first, then nearest base class.
        et = type(exc)
        if et in self.error_handlers:
            return self.error_handlers[et]
        for k, v in self.error_handlers.items():
            if isinstance(exc, k):
                return v
        return None

    async def _dispatch(self, req: Request) -> Response:
        early = await self._run_before_hooks(req)
        if early is not None:
            return early

        route, params = self._match_method(req.path, req.method)
        req.path_params = params
        resp = await self._call_endpoint(route.endpoint, req, params)
        resp = await self._run_after_hooks(req, resp)
        return resp

    def _allowed_methods_for_path(self, path: str) -> set[str]:
        methods: set[str] = set()
        for r in self.routes:
            if r.pattern.match(path):
                methods |= set(r.methods)
        if "GET" in methods:
            methods.add("HEAD")
        return methods

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "websocket":
            await self._handle_websocket(scope, receive, send)
            return
        if scope.get("type") == "lifespan":
            await self._handle_lifespan(receive, send)
            return
        if scope.get("type") != "http":
            return

        req = Request(scope=scope, receive=receive, send=send, max_body_size=self.max_body_size)
        token = _current_request.set(req)
        try:

            async def call_next(i: int = 0) -> Response:
                if i >= len(self.middlewares):
                    return await self._dispatch(req)

                mw = self.middlewares[i]

                async def nxt() -> Response:
                    return await call_next(i + 1)

                return await mw(req, nxt)

            # Automatic OPTIONS and HEAD support.
            if req.method == "OPTIONS":
                allowed = self._allowed_methods_for_path(req.path)
                if allowed:
                    allowed_with_opts = set(allowed) | {"OPTIONS"}
                    hdrs = {
                        "allow": ",".join(sorted(allowed_with_opts)),
                    }
                    resp = Response(b"", status=204, headers=hdrs)
                else:
                    resp = PlainTextResponse("Not Found", status=404)
                await resp(scope, receive, send)
                return

            is_head = req.method == "HEAD"
            if is_head:
                # Treat HEAD as GET for routing; body will be stripped later.
                req.scope = dict(req.scope)
                req.scope["method"] = "GET"

            try:
                resp = await call_next(0)
            except HTTPError as he:
                handler = self._find_error_handler(he)
                if handler is not None:
                    out = handler(req, he)
                    if inspect.isawaitable(out):
                        out = await t.cast(t.Awaitable, out)
                    resp = t.cast(Response, out)
                else:
                    error_headers = {}
                    if isinstance(he, MethodNotAllowed) and he.allowed:
                        error_headers["allow"] = ",".join(he.allowed)
                    if self.debug:
                        resp = PlainTextResponse(f"{he.status} {he.detail}", status=he.status, headers=error_headers)
                    else:
                        resp = PlainTextResponse(he.detail or "Error", status=he.status, headers=error_headers)
            except Exception as e:
                handler = self._find_error_handler(e)
                if handler is not None:
                    out = handler(req, e)
                    if inspect.isawaitable(out):
                        out = await t.cast(t.Awaitable, out)
                    resp = t.cast(Response, out)
                else:
                    if self.debug:
                        resp = PlainTextResponse(traceback.format_exc(), status=500)
                    else:
                        resp = PlainTextResponse("Internal Server Error", status=500)

            if is_head:
                # HEAD has no body, but preserves GET's representation metadata.
                content_length = resp.headers.get("content-length")
                resp.body = b""
                if content_length is not None:
                    resp.headers["content-length"] = content_length
                else:
                    resp.headers.pop("content-length", None)

            await resp(scope, receive, send)
        finally:
            _current_request.reset(token)

    async def _handle_lifespan(self, receive, send):
        while True:
            event = await receive()
            if event["type"] == "lifespan.startup":
                try:
                    for fn in self.startup_hooks:
                        result = fn()
                        if inspect.isawaitable(result):
                            await t.cast(t.Awaitable, result)
                except Exception as exc:
                    await send({"type": "lifespan.startup.failed", "message": str(exc)})
                else:
                    await send({"type": "lifespan.startup.complete"})
            elif event["type"] == "lifespan.shutdown":
                try:
                    for fn in reversed(self.shutdown_hooks):
                        result = fn()
                        if inspect.isawaitable(result):
                            await t.cast(t.Awaitable, result)
                except Exception as exc:
                    await send({"type": "lifespan.shutdown.failed", "message": str(exc)})
                else:
                    await send({"type": "lifespan.shutdown.complete"})
                return


# ----------------------------
# Helpers
# ----------------------------


def jsonify(data: t.Any, status: int = 200, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(data, status=status, headers=headers)


def text(s: str, status: int = 200, headers: dict[str, str] | None = None) -> PlainTextResponse:
    return PlainTextResponse(s, status=status, headers=headers)


def html(s: str, status: int = 200, headers: dict[str, str] | None = None) -> HTMLResponse:
    return HTMLResponse(s, status=status, headers=headers)


def redirect(location: str, status: int = 302, *, headers: dict[str, str] | None = None) -> Response:
    h = dict(headers or {})
    h["location"] = location
    return Response(b"", status=status, headers=h)


def clear_client_storage(
    *,
    cookies: t.Iterable[str] = (),
    status: int = 204,
    headers: dict[str, str] | None = None,
) -> Response:
    """Ask browsers to clear caches/storage and expire selected cookies.

    Browser JavaScript localStorage cannot be deleted by a server directly;
    ``Clear-Site-Data`` is the HTTP-level mechanism for this request.
    """
    h = dict(headers or {})
    h.setdefault("cache-control", "no-store")
    h.setdefault("clear-site-data", '"cache", "storage"')
    raw = [("set-cookie", f"{name}=; Max-Age=0; Path=/; HttpOnly") for name in cookies]
    return Response(b"", status=status, headers=h, raw_headers=raw)


def query_result(
    data: t.Any,
    *,
    content_location: str | None = None,
    cache_seconds: int | None = None,
) -> JSONResponse:
    """Return a cache-aware result for a QUERY endpoint."""
    headers: dict[str, str] = {}
    if content_location is not None:
        headers["content-location"] = content_location
    if cache_seconds is not None:
        headers["cache-control"] = f"public, max-age={int(cache_seconds)}"
    return JSONResponse(data, headers=headers)


def stream(
    body_iter: t.AsyncIterable[t.Union[str, bytes, bytearray]] | t.Iterable[t.Union[str, bytes, bytearray]],
    *,
    status: int = 200,
    headers: dict[str, str] | None = None,
    content_type: str | None = "application/octet-stream",
) -> StreamingResponse:
    return StreamingResponse(body_iter, status=status, headers=headers, content_type=content_type)


def send_file(
    path: str,
    *,
    req: Request | None = None,
    status: int = 200,
    headers: dict[str, str] | None = None,
    download_name: str | None = None,
    cache_seconds: int | None = 3600,
) -> FileResponse:
    return FileResponse(
        path,
        req=req,
        status=status,
        headers=headers,
        download_name=download_name,
        cache_seconds=cache_seconds,
    )


def static(
    root: str,
    *,
    url_prefix: str = "/static",
    cache_seconds: int | None = 3600,
) -> Router:
    """Create a router that serves files under root at url_prefix.

    Example:
        app.mount("", static("./public"))
        # GET /static/app.js -> ./public/app.js
    """

    r = Router()

    @r.get(url_prefix + "/<path:path>", name="static")
    def _static(path: str):
        req = request()
        full = _safe_join(root, path)
        if not os.path.exists(full) or not os.path.isfile(full):
            raise NotFound()
        return FileResponse(full, req=req, cache_seconds=cache_seconds)

    return r


# ----------------------------
# Built-in middleware
# ----------------------------


def logger_middleware(*, print_fn=print) -> Middleware:
    async def _mw(req: Request, call_next):
        loop = asyncio.get_event_loop()
        start = loop.time()
        resp = await call_next()
        dur_ms = (loop.time() - start) * 1000
        print_fn(f"[night] {req.method} {req.path} -> {resp.status} ({dur_ms:.1f}ms)")
        return resp

    return _mw


def cors_middleware(
    *,
    allow_origin: str = "*",
    allow_methods: str = "GET,POST,PUT,DELETE,OPTIONS",
    allow_headers: str = "*",
) -> Middleware:
    async def _mw(req: Request, call_next):
        if req.method == "OPTIONS":
            return Response(
                b"",
                status=204,
                headers={
                    "access-control-allow-origin": allow_origin,
                    "access-control-allow-methods": allow_methods,
                    "access-control-allow-headers": allow_headers,
                },
            )
        resp = await call_next()
        resp.headers.setdefault("access-control-allow-origin", allow_origin)
        resp.headers.setdefault("access-control-allow-methods", allow_methods)
        resp.headers.setdefault("access-control-allow-headers", allow_headers)
        return resp

    return _mw


# ----------------------------
# Example usage
# ----------------------------


def create_app(debug: bool = False) -> Night:
    app = Night(debug=debug)

    # app.use(logger_middleware())

    @app.before_request
    def _add_req_id(req: Request):
        # Example of a before_request hook. Add a simple request id header.
        req.state["request_id"] = os.urandom(8).hex()
        return None

    @app.after_request
    def _add_server_header(req: Request, resp: Response):
        resp.headers.setdefault("server", "night")
        resp.headers.setdefault("x-request-id", str(req.state.get("request_id", "")))
        return resp

    @app.errorhandler(KeyError)
    def _key_error(req: Request, exc: Exception):
        # Example custom error handler.
        return jsonify({"error": "key_error", "detail": str(exc)}, status=400)

    @app.get("/", name="index")
    async def index(req: Request):
        return html(
            """<!doctype html><html><head><meta charset='utf-8'><title>night</title></head>
<body><h1>night</h1><p>It works.</p><p><a href='/health'>health</a></p></body></html>"""
        )

    @app.get("/health", name="health")
    def health():
        return {"ok": True, "ts": _dt.datetime.now().isoformat()}

    @app.get("/hello/<name>", name="hello")
    def hello(name: str):
        # Demonstrate query params: /hello/bob?title=Mr
        q = request().query
        title = q.get("title")
        if isinstance(title, list):
            title = title[0] if title else None
        if title:
            return {"hello": f"{title} {name}"}
        return {"hello": name}

    @app.get("/links", name="links")
    def links():
        return {
            "index": app.url_for("index"),
            "hello": app.url_for("hello", name="night", title="Captain"),
        }

    @app.post("/echo", name="echo")
    async def echo(req: Request):
        data = await req.json()
        return jsonify({"you_sent": data, "cookies": req.cookies, "client": req.client, "url": req.url})

    @app.get("/stream", name="stream")
    async def stream_demo(req: Request):
        async def gen():
            for i in range(5):
                yield f"chunk {i}\n"
                await asyncio.sleep(0.05)

        return StreamingResponse(gen(), content_type="text/plain; charset=utf-8")

    # Mount a static router example if ./public exists.
    pub = os.path.join(os.path.dirname(__file__), "public")
    if os.path.isdir(pub):
        app.mount("", static(pub))

    return app


# ASGI entrypoint convention: `app`
app = create_app(debug=bool(os.environ.get("NIGHT_DEBUG")))


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="night")
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("module")
    run_parser.add_argument("--host", default="127.0.0.1")
    run_parser.add_argument("--port", type=int, default=8000)
    sub.add_parser("routes")
    sub.add_parser("shell")
    args = parser.parse_args(argv)

    if args.command == "routes":
        for route in app.routes:
            print(f"{','.join(sorted(route.methods)):20} {route.raw_path}")
        for route in app.websocket_routes:
            print(f"WEBSOCKET             {route.raw_path}")
        return 0
    if args.command in {"run", "shell"}:
        namespace = runpy.run_path(args.module) if args.command == "run" else globals()
        target = namespace.get("app", app)
        if args.command == "shell":
            import code
            code.interact(local={"app": target, **namespace})
            return 0
        import uvicorn
        uvicorn.run(target, host=args.host, port=args.port)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(cli(sys.argv[1:]))
