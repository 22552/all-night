"""Cloudflare Workers adapter for Night.

Keeps Cloudflare-specific request metadata out of the core framework while
exposing it through Night's normal ``req.info`` API.
"""

from __future__ import annotations

import typing as t


def _plain(value: t.Any) -> t.Any:
    if value is None:
        return None
    try:
        return value.to_py()
    except Exception:
        return value


def _cf_value(cf: t.Any, name: str) -> t.Any:
    if cf is None:
        return None
    if isinstance(cf, dict):
        return cf.get(name)
    try:
        return getattr(cf, name)
    except Exception:
        try:
            return cf[name]
        except Exception:
            return None


def cloudflare_info(request: t.Any) -> dict[str, t.Any]:
    """Extract normalized Cloudflare metadata from a Workers Request."""
    headers = getattr(request, "headers", None)

    def header(name: str) -> str | None:
        if headers is None:
            return None
        try:
            value = headers.get(name)
        except Exception:
            try:
                value = dict(headers).get(name)
            except Exception:
                value = None
        return str(value) if value not in (None, "") else None

    cf = _plain(getattr(request, "cf", None))
    info = {
        "platform": "cloudflare",
        "client_ip": header("CF-Connecting-IP"),
        "request_id": header("CF-Ray"),
        "country": _cf_value(cf, "country") or header("CF-IPCountry"),
        "city": _cf_value(cf, "city"),
        "region": _cf_value(cf, "region"),
        "timezone": _cf_value(cf, "timezone"),
        "latitude": _cf_value(cf, "latitude"),
        "longitude": _cf_value(cf, "longitude"),
        "colo": _cf_value(cf, "colo"),
        "asn": _cf_value(cf, "asn"),
        "as_organization": _cf_value(cf, "asOrganization"),
        "http_protocol": _cf_value(cf, "httpProtocol"),
        "tls_version": _cf_value(cf, "tlsVersion"),
        "tls_cipher": _cf_value(cf, "tlsCipher"),
        "client_tcp_rtt": _cf_value(cf, "clientTcpRtt"),
        "client_quic_rtt": _cf_value(cf, "clientQuicRtt"),
        "client_quic_delivery_rate": _cf_value(cf, "clientQuicDeliveryRate"),
        "user_agent": header("User-Agent"),
        "accept_language": header("Accept-Language"),
        "referrer": header("Referer"),
    }
    return {key: _plain(value) for key, value in info.items() if value not in (None, "")}


async def cloudflare(app: t.Any, request: t.Any, *, response_class: t.Any = None) -> t.Any:
    """Serve a Cloudflare Workers Request through Night.

    Usage::

        from night_cloudflare import cloudflare

        async def on_fetch(request):
            return await cloudflare(app, request)
    """
    from night_web import handle_web

    if response_class is None:
        try:
            from workers import Response as response_class
        except ImportError as exc:
            raise RuntimeError("Cloudflare adapter requires workers-runtime-sdk") from exc

    method_value = getattr(request.method, "value", request.method)
    method = str(method_value).upper()
    body = b""
    if method not in {"GET", "HEAD"}:
        if hasattr(request, "bytes"):
            body = bytes(await request.bytes())
        else:
            raw = await request.arrayBuffer()
            try:
                body = bytes(raw.to_py())
            except Exception:
                body = bytes(raw)

    header_source = getattr(request, "headers", ())
    try:
        headers = list(header_source.items())
    except Exception:
        try:
            headers = list(dict(header_source).items())
        except Exception:
            headers = []

    result = await handle_web(
        app,
        method=method,
        url=str(request.url),
        headers=headers,
        body=body,
        platform_info=cloudflare_info(request),
    )
    return response_class(result.body, status=result.status, headers=result.headers)


__all__ = ["cloudflare", "cloudflare_info"]
