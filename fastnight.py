"""Experimental Night hot-path optimizations.

The fastNight branch keeps changes isolated until benchmarks show a repeatable
win. This revision focuses only on response construction/header encoding; route
matching and dispatch behavior stay identical to Night.
"""

from __future__ import annotations

import json
import typing as t

from night import FileHandler, Night, Request, Response, _cached_http_date, request

_JSON_CT = "application/json; charset=utf-8"
_TEXT_CT = "text/plain; charset=utf-8"


class _FastResponse(Response):
    """Response variant that encodes ASGI headers once at construction time."""

    __slots__ = ("status", "body", "headers", "raw_headers", "_asgi_headers")

    def __init__(
        self,
        body: bytes,
        *,
        status: int = 200,
        content_type: str | None = None,
    ):
        self.status = int(status)
        self.body = body
        self.raw_headers = []

        length = str(len(body))
        date = _cached_http_date()
        if content_type is None:
            self.headers = {
                "date": date,
                "content-length": length,
            }
            self._asgi_headers = [
                (b"date", date.encode("latin-1")),
                (b"content-length", length.encode("ascii")),
            ]
        else:
            self.headers = {
                "content-type": content_type,
                "date": date,
                "content-length": length,
            }
            self._asgi_headers = [
                (b"content-type", content_type.encode("latin-1")),
                (b"date", date.encode("latin-1")),
                (b"content-length", length.encode("ascii")),
            ]

    def asgi_headers(self) -> list[tuple[bytes, bytes]]:
        return self._asgi_headers

    def add_header(self, name: str, value: str):
        # Preserve Response mutation semantics for cookies/middleware. Once a
        # header is added, update both public representations together.
        lname = name.lower()
        self.raw_headers.append((lname, value))
        self._asgi_headers.append((lname.encode("latin-1"), value.encode("latin-1")))

    async def __call__(self, scope, receive, send):
        await send({
            "type": "http.response.start",
            "status": self.status,
            "headers": self._asgi_headers,
        })
        await send({
            "type": "http.response.body",
            "body": self.body,
            "more_body": False,
        })


class FastNight(Night):
    """Night with response-construction shortcuts only."""

    def _coerce_response(self, value: t.Any) -> Response:
        if isinstance(value, FileHandler):
            return value.response(request())

        kind = type(value)
        if kind is dict or kind is list:
            body = json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            return _FastResponse(body, content_type=_JSON_CT)
        if kind is str:
            return _FastResponse(value.encode("utf-8"), content_type=_TEXT_CT)
        if kind is bytes:
            return _FastResponse(value)
        if value is None:
            return _FastResponse(b"", status=204)
        if isinstance(value, Response):
            return value
        if kind is bytearray:
            return _FastResponse(bytes(value))
        return _FastResponse(str(value).encode("utf-8"), content_type=_TEXT_CT)


__all__ = ["FastNight"]
