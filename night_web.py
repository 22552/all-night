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


def _platform_metadata(headers: list[tuple[str, str]]) -> dict[str, t.Any]:
    """Normalize trusted edge metadata exposed through platform headers.

    Generic proxy headers such as ``X-Forwarded-For`` are intentionally not
    trusted here. The adapter only consumes platform-owned headers with clear
    semantics, while ordinary ASGI servers can populate ``scope`` directly.
    """
    values = {key.lower(): value.strip() for key, value in headers}
    info: dict[str, t.Any] = {}

    if values.get("cf-ray") or values.get("cf-connecting-ip"):
        info["platform"] = "cloudflare"
        info["client_ip"] = values.get("cf-connecting-ip")
        info["request_id"] = values.get("cf-ray")
        info["country"] = values.get("cf-ipcountry")
        info["city"] = values.get("cf-ipcity")
        info["region"] = values.get("cf-region")
        info["region_code"] = values.get("cf-region-code")
        info["postal_code"] = values.get("cf-postal-code")
        info["timezone"] = values.get("cf-timezone")
        info["continent"] = values.get("cf-ipcontinent")
        info["latitude"] = values.get("cf-iplatitude")
        info["longitude"] = values.get("cf-iplongitude")
    elif any(key.startswith("x-nf-") for key in values):
        info["platform"] = "netlify"
        info["client_ip"] = values.get("x-nf-client-connection-ip")
        info["request_id"] = values.get("x-nf-request-id")
    elif any(key.startswith("x-vercel-") for key in values):
        info["platform"] = "vercel"
        info["client_ip"] = values.get("x-real-ip")
        info["request_id"] = values.get("x-vercel-id")
        info["country"] = values.get("x-vercel-ip-country")
        info["city"] = values.get("x-vercel-ip-city")
        info["region"] = values.get("x-vercel-ip-country-region")
        info["latitude"] = values.get("x-vercel-ip-latitude")
        info["longitude"] = values.get("x-vercel-ip-longitude")

    info["user_agent"] = values.get("user-agent")
    info["accept_language"] = values.get("accept-language")
    info["referrer"] = values.get("referer")
    return {key: value for key, value in info.items() if value not in (None, "")}


async def handle_web(
    app: t.Any,
    *,
    method: str,
    url: str,
    headers: t.Any = None,
    body: bytes | bytearray | memoryview = b"",
    client: tuple[str, int] | None = None,
    platform_info: dict[str, t.Any] | None = None,
) -> WebResult:
    """Run a buffered Web-style HTTP request through a Night ASGI app.

    JavaScript hosts can convert a standard ``Request`` into ordinary Python
    primitives and call this function through Pyodide. Known edge metadata is
    normalized into ``scope['state']['night_request_info']`` so Night exposes a
    stable API independent of the deployment platform.
    """

    parsed = urllib.parse.urlsplit(str(url))
    method = str(method).upper()
    body_bytes = bytes(body)
    max_body_size = getattr(app, "max_body_size", None)
    if max_body_size is not None and len(body_bytes) > int(max_body_size):
        return WebResult(
            413,
            [("content-type", "text/plain; charset=utf-8")],
            b"Request body too large",
        )

    encoded_path = parsed.path or "/"
    decoded_path = urllib.parse.unquote(encoded_path)
    scheme = parsed.scheme or "https"
    port = parsed.port or (443 if scheme == "https" else 80)
    header_pairs = _header_pairs(headers)
    info = _platform_metadata(header_pairs)
    if platform_info:
        info.update({str(key): value for key, value in platform_info.items() if value is not None})

    if client is None and info.get("client_ip"):
        client = (str(info["client_ip"]), 0)

    header_bytes = [
        (str(key).lower().encode("latin-1"), str(value).encode("latin-1"))
        for key, value in header_pairs
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
        "state": {"night_request_info": info},
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
