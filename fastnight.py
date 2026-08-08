"""Experimental Night hot-path optimizations.

This module intentionally keeps the public Night API while specializing the
most common small-service path: HTTP GET routes with no middleware/hooks.
It exists on the fastNight branch so optimizations can be benchmarked before
moving them into the single-file core.
"""

from __future__ import annotations

import json
import typing as t

from night import (
    Night,
    Request,
    Response,
    FileHandler,
    ROUTE_CALL_DIRECT_PARAM,
    ROUTE_CALL_NOARGS,
    request,
)

_JSON_CONTENT_TYPE = b"application/json; charset=utf-8"
_TEXT_CONTENT_TYPE = b"text/plain; charset=utf-8"


class _FastResponse(Response):
    """Response with ASGI-ready headers cached at construction time."""

    __slots__ = ("status", "body", "headers", "raw_headers", "_asgi_headers")

    def __init__(self, body: bytes, *, status: int = 200,
                 content_type: bytes | None = None):
        self.status = status
        self.body = body
        self.raw_headers = []
        length = str(len(body))
        length_b = length.encode("ascii")
        if content_type is None:
            self.headers = {"content-length": length}
            self._asgi_headers = ((b"content-length", length_b),)
        else:
            self.headers = {
                "content-type": content_type.decode("latin-1"),
                "content-length": length,
            }
            self._asgi_headers = (
                (b"content-type", content_type),
                (b"content-length", length_b),
            )

    def asgi_headers(self):
        return self._asgi_headers

    async def __call__(self, scope, receive, send):
        await send({"type": "http.response.start", "status": self.status,
                    "headers": self._asgi_headers})
        await send({"type": "http.response.body", "body": self.body,
                    "more_body": False})


class FastNight(Night):
    """Experimental Night subclass with conservative hot-path shortcuts."""

    def _coerce_response(self, value: t.Any) -> Response:
        if isinstance(value, FileHandler):
            return value.response(request())
        kind = type(value)
        if kind is dict or kind is list:
            # Match Night's compact JSON output but skip temporary header dict
            # normalization and per-request header latin-1 encoding.
            body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            return _FastResponse(body, content_type=_JSON_CONTENT_TYPE)
        if kind is str:
            return _FastResponse(value.encode("utf-8"), content_type=_TEXT_CONTENT_TYPE)
        if kind is bytes:
            return _FastResponse(value)
        if value is None:
            return _FastResponse(b"", status=204)
        if isinstance(value, Response):
            return value
        if kind is bytearray:
            return _FastResponse(bytes(value))
        return _FastResponse(str(value).encode("utf-8"), content_type=_TEXT_CONTENT_TYPE)

    async def _dispatch(self, req: Request, path: str | None = None,
                        method: str | None = None) -> Response:
        path = req.path if path is None else path
        method = req.method if method is None else method

        # Static no-argument routes are the most common microservice/health/API
        # benchmark path. Avoid path normalization, tuple allocation, params
        # mutation and the generic matcher when no hooks need to observe them.
        if not self.before_hooks and not self.after_hooks:
            method_routes = self._static_method_index.get(method)
            if method_routes is not None:
                route = method_routes.get(path)
                if route is None and path != "/" and path.endswith("/"):
                    route = method_routes.get(path.rstrip("/"))
                if route is not None and route._night_call_kind == ROUTE_CALL_NOARGS:
                    invoke = route._night_invoke
                    if route._night_invoke_async:
                        return await invoke(req, req.path_params)
                    return invoke(req, req.path_params)

            # Single one-parameter dynamic route: avoid allocating the
            # (route, value) pair returned by _match_direct_for_dispatch().
            routes = self._dynamic_method_routes.get(method)
            if routes and len(routes) == 1:
                route = routes[0]
                if route._night_call_kind == ROUTE_CALL_DIRECT_PARAM and route._night_simple_dynamic is not None:
                    key = path if path == "/" or not path.endswith("/") else path.rstrip("/")
                    value = self._simple_dynamic_value(route, key)
                    if value is not None:
                        req.path_params[route._night_direct_param] = value
                        invoke = route._night_invoke_scalar
                        if route._night_invoke_async:
                            return await invoke(value)
                        return invoke(value)

        return await super()._dispatch(req, path, method)


__all__ = ["FastNight"]
