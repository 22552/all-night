"""tnight - Byakuya, the tiny dependency-free HTTP/ASGI core extracted from Night.

Distribution name: ``byakuya``
Import module: ``tnight``
"""
from __future__ import annotations

import inspect
import json
import re
import typing as t
import urllib.parse

__version__ = "0.1.0"
MAX_BODY_SIZE = 16 * 1024 * 1024


class HTTPError(Exception):
    def __init__(self, status: int, detail: str = "") -> None:
        self.status = int(status)
        self.detail = detail
        super().__init__(f"HTTP {self.status}: {detail}")


class NotFound(HTTPError):
    def __init__(self, detail: str = "Not Found") -> None:
        super().__init__(404, detail)


class MethodNotAllowed(HTTPError):
    def __init__(self, allowed: t.Iterable[str]) -> None:
        self.allowed = tuple(sorted(set(allowed)))
        super().__init__(405, "Method Not Allowed")


class Request:
    __slots__ = ("scope", "method", "path", "query_string", "query", "headers", "body", "path_params")

    def __init__(self, scope: dict[str, t.Any], body: bytes = b"", path_params: dict[str, t.Any] | None = None):
        self.scope = scope
        self.method = str(scope.get("method", "GET")).upper()
        self.path = scope.get("path", "/") or "/"
        self.query_string = scope.get("query_string", b"") or b""
        parsed = urllib.parse.parse_qs(self.query_string.decode("latin-1"), keep_blank_values=True)
        self.query = {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}
        self.headers = {
            k.decode("latin-1").lower(): v.decode("latin-1")
            for k, v in scope.get("headers", ())
        }
        self.body = body
        self.path_params = path_params or {}

    def json(self) -> t.Any:
        return None if not self.body else json.loads(self.body)

    def text(self, encoding: str = "utf-8") -> str:
        return self.body.decode(encoding)


class Response:
    media_type = "application/octet-stream"

    def __init__(self, body: str | bytes | bytearray = b"", status: int = 200,
                 headers: t.Mapping[str, str] | None = None, media_type: str | None = None) -> None:
        self.body = body.encode() if isinstance(body, str) else bytes(body)
        self.status = int(status)
        self.headers = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
        if media_type is not None:
            self.media_type = media_type
        self.headers.setdefault("content-type", self.media_type)
        self.headers.setdefault("content-length", str(len(self.body)))

    async def send_asgi(self, send: t.Callable[..., t.Awaitable[None]], *, head: bool = False) -> None:
        await send({
            "type": "http.response.start",
            "status": self.status,
            "headers": [(k.encode("latin-1"), v.encode("latin-1")) for k, v in self.headers.items()],
        })
        await send({"type": "http.response.body", "body": b"" if head else self.body})


class PlainTextResponse(Response):
    media_type = "text/plain; charset=utf-8"


class HTMLResponse(Response):
    media_type = "text/html; charset=utf-8"


class JSONResponse(Response):
    media_type = "application/json"

    def __init__(self, data: t.Any, status: int = 200, headers: t.Mapping[str, str] | None = None) -> None:
        super().__init__(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode(), status, headers)


class _Route:
    __slots__ = ("path", "methods", "endpoint", "regex", "converters")

    def __init__(self, path: str, methods: t.Iterable[str], endpoint: t.Callable[..., t.Any]) -> None:
        self.path = path
        self.methods = frozenset(m.upper() for m in methods)
        self.endpoint = endpoint
        self.converters: dict[str, t.Callable[[str], t.Any]] = {}
        pattern = "^"
        pos = 0
        for match in re.finditer(r"<(?:(int|str):)?([A-Za-z_]\w*)>", path):
            pattern += re.escape(path[pos:match.start()])
            kind, name = match.groups()
            if kind == "int":
                pattern += fr"(?P<{name}>\d+)"
                self.converters[name] = int
            else:
                pattern += fr"(?P<{name}>[^/]+)"
                self.converters[name] = str
            pos = match.end()
        pattern += re.escape(path[pos:]) + "$"
        self.regex = re.compile(pattern)

    def match(self, path: str) -> dict[str, t.Any] | None:
        found = self.regex.match(path)
        if not found:
            return None
        return {k: self.converters[k](v) for k, v in found.groupdict().items()}


class Night:
    def __init__(self, *, max_body_size: int = MAX_BODY_SIZE) -> None:
        self.max_body_size = int(max_body_size)
        self._routes: list[_Route] = []

    def route(self, path: str, *, methods: t.Iterable[str] = ("GET",)):
        def decorator(fn: t.Callable[..., t.Any]):
            self._routes.append(_Route(path, methods, fn))
            return fn
        return decorator

    def get(self, path: str):
        return self.route(path, methods=("GET",))

    def post(self, path: str):
        return self.route(path, methods=("POST",))

    def put(self, path: str):
        return self.route(path, methods=("PUT",))

    def patch(self, path: str):
        return self.route(path, methods=("PATCH",))

    def delete(self, path: str):
        return self.route(path, methods=("DELETE",))

    def _resolve(self, method: str, path: str) -> tuple[_Route, dict[str, t.Any]]:
        allowed: set[str] = set()
        effective = "GET" if method == "HEAD" else method
        for route in self._routes:
            params = route.match(path)
            if params is None:
                continue
            allowed.update(route.methods)
            if effective in route.methods:
                return route, params
        if allowed:
            if "GET" in allowed:
                allowed.add("HEAD")
            allowed.add("OPTIONS")
            raise MethodNotAllowed(allowed)
        raise NotFound()

    async def dispatch(self, request: Request) -> Response:
        if request.method == "OPTIONS":
            allowed: set[str] = set()
            for route in self._routes:
                if route.match(request.path) is not None:
                    allowed.update(route.methods)
            if not allowed:
                raise NotFound()
            if "GET" in allowed:
                allowed.add("HEAD")
            allowed.add("OPTIONS")
            return Response(b"", 204, {"allow": ", ".join(sorted(allowed))})

        route, params = self._resolve(request.method, request.path)
        request.path_params = params
        sig = inspect.signature(route.endpoint)
        kwargs = dict(params)
        args: list[t.Any] = []
        if sig.parameters:
            first = next(iter(sig.parameters.values()))
            if first.name in {"request", "req"}:
                args.append(request)
        result = route.endpoint(*args, **kwargs)
        if inspect.isawaitable(result):
            result = await result
        return self._coerce_response(result)

    @staticmethod
    def _coerce_response(value: t.Any) -> Response:
        if isinstance(value, Response):
            return value
        if isinstance(value, (dict, list, tuple)):
            return JSONResponse(value)
        if isinstance(value, str):
            return PlainTextResponse(value)
        if isinstance(value, (bytes, bytearray)):
            return Response(value)
        if value is None:
            return Response(b"", 204)
        return PlainTextResponse(str(value))

    async def __call__(self, scope: dict[str, t.Any], receive: t.Callable[..., t.Awaitable[dict]],
                       send: t.Callable[..., t.Awaitable[None]]) -> None:
        if scope.get("type") != "http":
            raise RuntimeError("Byakuya/tnight only supports ASGI HTTP")
        chunks: list[bytes] = []
        size = 0
        more = True
        while more:
            event = await receive()
            if event.get("type") != "http.request":
                continue
            chunk = event.get("body", b"")
            size += len(chunk)
            if size > self.max_body_size:
                response = PlainTextResponse("Request body too large", 413)
                await response.send_asgi(send)
                return
            chunks.append(chunk)
            more = bool(event.get("more_body"))
        request = Request(scope, b"".join(chunks))
        try:
            response = await self.dispatch(request)
        except MethodNotAllowed as exc:
            response = PlainTextResponse(exc.detail, exc.status, {"allow": ", ".join(exc.allowed)})
        except HTTPError as exc:
            response = PlainTextResponse(exc.detail or "Error", exc.status)
        await response.send_asgi(send, head=request.method == "HEAD")


TinyNight = Night
App = Night


def jsonify(data: t.Any, status: int = 200, headers: t.Mapping[str, str] | None = None) -> JSONResponse:
    return JSONResponse(data, status, headers)


def text(body: str, status: int = 200, headers: t.Mapping[str, str] | None = None) -> PlainTextResponse:
    return PlainTextResponse(body, status, headers)


def html(body: str, status: int = 200, headers: t.Mapping[str, str] | None = None) -> HTMLResponse:
    return HTMLResponse(body, status, headers)


__all__ = [
    "App", "Night", "TinyNight", "Request", "Response", "PlainTextResponse",
    "HTMLResponse", "JSONResponse", "HTTPError", "NotFound", "MethodNotAllowed",
    "jsonify", "text", "html", "MAX_BODY_SIZE",
]
