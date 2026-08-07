"""Portable request metadata helpers for Night.

This module reads normalized metadata placed in ASGI ``scope['state']`` by
platform adapters such as ``night_web`` and exposes a small stable API.
"""

from __future__ import annotations

from dataclasses import dataclass
import typing as t


@dataclass(slots=True, frozen=True)
class RequestInfo:
    platform: str | None = None
    client_ip: str | None = None
    user_agent: str | None = None
    request_id: str | None = None
    country: str | None = None
    city: str | None = None
    region: str | None = None
    timezone: str | None = None
    latitude: str | None = None
    longitude: str | None = None
    accept_language: str | None = None
    referrer: str | None = None


def from_scope(scope: dict[str, t.Any]) -> RequestInfo:
    state = scope.get("state")
    if not isinstance(state, dict):
        state = {}
    raw = state.get("night_request_info")
    if not isinstance(raw, dict):
        raw = {}

    client_ip = raw.get("client_ip")
    if not client_ip:
        client = scope.get("client")
        try:
            client_ip = str(client[0]) if client else None
        except Exception:
            client_ip = None

    headers: dict[str, str] = {}
    for key, value in scope.get("headers") or ():
        try:
            headers[key.decode("latin-1").lower()] = value.decode("latin-1")
        except Exception:
            continue

    return RequestInfo(
        platform=_text(raw.get("platform")),
        client_ip=_text(client_ip),
        user_agent=_text(raw.get("user_agent") or headers.get("user-agent")),
        request_id=_text(raw.get("request_id")),
        country=_text(raw.get("country")),
        city=_text(raw.get("city")),
        region=_text(raw.get("region")),
        timezone=_text(raw.get("timezone")),
        latitude=_text(raw.get("latitude")),
        longitude=_text(raw.get("longitude")),
        accept_language=_text(raw.get("accept_language") or headers.get("accept-language")),
        referrer=_text(raw.get("referrer") or headers.get("referer")),
    )


def _text(value: t.Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = ["RequestInfo", "from_scope"]
