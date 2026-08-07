"""Portable Web Request adapter for Night.

This module turns Web-platform request primitives into Night's ASGI interface.
It intentionally has no platform SDK dependency, so the same bridge can be
used from Pyodide hosts such as Netlify Functions, Deno, Bun, or browsers.
"""

from __future__ import annotations

from dataclasses import dataclass
import typing as t
import urllib.parse


@dataclass(slots=True)
class WebResult:
    """Buffered HTTP response returned by :func:`handle_web`."""

    status: int
    headers: list[tuple[str, str]]
    body: bytes

    def as_tuple(self) -> tuple[int, list[tuple[str, str]], bytes]:
        return self.status, self.headers, self.body


def _header_pairs(headers: t.Any) -> list[tuple[str, str]]:
    if headers is None:
        return []
    if isinstance(headers, dict):
        items = headers.items()
    else:
        try:
            items = headers.items()
        except (AttributeError, TypeError):
            items = headers
    return [(str(key), str(value)) for key, value in items]


async def handle_web(
    app: t.Any,
    *,
    method: str,
    url: str,
    headers: t.Any = None,
    body: bytes | bytearray | memoryview = b"",
    client: tuple[str, int] | None = None,
) -> WebResult:
    """Run a buffered Web-style HTTP request through a Night ASGI app.

    The adapter only accepts ordinary Python primitives. JavaScript hosts can
    therefore convert a standard ``Request`` into ``method``/``url``/headers/
    body and call this function through Pyodide without importing any host SDK
    into Night itself.
    """

    parsed = urllib.parse.urlsplit(str(url))
    method = str(method).upper()
    body_bytes = bytes(body)
    max_body_size = getattr(app, "max_body_size", None)
    if max_body_size is not None and len(body_bytes) > int(max_body_size):
        # Avoid importing Night's HTTPError here: this module also works with
        # any ASGI application exposing the same primitives.
        return WebResult(
            413,
            [("content-type", "text/plain; charset=utf-8")],
            b"Request body too large",
        )

    encoded_path = parsed.path or "/"
    decoded_path = urllib.parse.unquote(encoded_path)
    scheme = parsed.scheme or "https"
    port = parsed.port or (443 if scheme == "https" else 80)
    header_bytes = [
        (str(key).lower().encode("latin-1"), str(value).encode("latin-1"))
        for key, value in _header_pairs(headers)
    ]

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": scheme,
        "path": decoded_path,
        "raw_path": encoded_path.encode("utf-8"),
        "query_string": parsed.query.encode("latin-1"),
        "headers": header_bytes,
        "server": (parsed.hostname or "web", port),
        "client": client,
    }

    received = False

    async def receive():
        nonlocal received
        if received:
            return {"type": "http.request", "body": b"", "more_body": False}
        received = True
        return {"type": "http.request", "body": body_bytes, "more_body": False}

    events: list[dict[str, t.Any]] = []

    async def send(event):
        events.append(event)

    await app(scope, receive, send)

    start = next(
        (event for event in events if event.get("type") == "http.response.start"),
        None,
    )
    if start is None:
        raise RuntimeError("Night produced no HTTP response start event")

    chunks = [
        bytes(event.get("body", b""))
        for event in events
        if event.get("type") == "http.response.body"
    ]
    response_headers = [
        (key.decode("latin-1"), value.decode("latin-1"))
        for key, value in start.get("headers", ())
    ]
    return WebResult(int(start["status"]), response_headers, b"".join(chunks))


__all__ = ["WebResult", "handle_web"]
