"""Scoped multi-session routing for Midnight.

F = logical/session metadata
G = browser-tab metadata (stable across WebSocket reconnects)
S = WebSocket metadata (reset on disconnect)
Q = application-defined metadata

Filters are represented as JSON-serializable ASTs so the same API can later be
forwarded through Redis/NATS/etc. without serializing Python callables.
"""

from __future__ import annotations

import contextlib
import contextvars
import secrets
import typing as t

from night_midnight import CompiledMidnight, MidnightWebSocketAdapter, trusted_session_id


_JSON_VALUE = str | int | float | bool | None | list[t.Any] | dict[str, t.Any]


class FilterExpr:
    __slots__ = ("node",)

    def __init__(self, node: dict[str, t.Any]) -> None:
        self.node = node

    def __and__(self, other: "FilterExpr") -> "FilterExpr":
        return FilterExpr({"op": "and", "args": [self.node, _filter(other).node]})

    def __or__(self, other: "FilterExpr") -> "FilterExpr":
        return FilterExpr({"op": "or", "args": [self.node, _filter(other).node]})

    def __invert__(self) -> "FilterExpr":
        return FilterExpr({"op": "not", "arg": self.node})

    def to_dict(self) -> dict[str, t.Any]:
        return dict(self.node)


class FilterField:
    __slots__ = ("scope", "path")

    def __init__(self, scope: str, path: tuple[str, ...]) -> None:
        self.scope = scope
        self.path = path

    def __getattr__(self, name: str) -> "FilterField":
        if name.startswith("_"):
            raise AttributeError(name)
        return FilterField(self.scope, (*self.path, name))

    def _cmp(self, op: str, value: t.Any) -> FilterExpr:
        return FilterExpr({"op": op, "scope": self.scope, "path": list(self.path), "value": value})

    def __eq__(self, value: t.Any) -> FilterExpr:  # type: ignore[override]
        return self._cmp("eq", value)

    def __ne__(self, value: t.Any) -> FilterExpr:  # type: ignore[override]
        return self._cmp("ne", value)

    def __lt__(self, value: t.Any) -> FilterExpr:
        return self._cmp("lt", value)

    def __le__(self, value: t.Any) -> FilterExpr:
        return self._cmp("le", value)

    def __gt__(self, value: t.Any) -> FilterExpr:
        return self._cmp("gt", value)

    def __ge__(self, value: t.Any) -> FilterExpr:
        return self._cmp("ge", value)

    def in_(self, values: t.Iterable[t.Any]) -> FilterExpr:
        return self._cmp("in", list(values))

    def contains(self, value: t.Any) -> FilterExpr:
        return self._cmp("contains", value)

    def exists(self) -> FilterExpr:
        return FilterExpr({"op": "exists", "scope": self.scope, "path": list(self.path)})


class FilterNamespace:
    __slots__ = ("scope",)

    def __init__(self, scope: str) -> None:
        self.scope = scope

    def __getattr__(self, name: str) -> FilterField:
        if name.startswith("_"):
            raise AttributeError(name)
        return FilterField(self.scope, (name,))


F = FilterNamespace("F")
G = FilterNamespace("G")
S = FilterNamespace("S")
Q = FilterNamespace("Q")


def _filter(value: FilterExpr) -> FilterExpr:
    if not isinstance(value, FilterExpr):
        raise TypeError("Midnight filters must be built from F/G/S/Q fields")
    return value


def _get_path(value: t.Any, path: list[str]) -> tuple[bool, t.Any]:
    current = value
    for part in path:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return False, None
    return True, current


def match_filter(node: dict[str, t.Any], scopes: dict[str, dict[str, t.Any]]) -> bool:
    op = str(node.get("op", ""))
    if op == "and":
        return all(match_filter(item, scopes) for item in node.get("args", []))
    if op == "or":
        return any(match_filter(item, scopes) for item in node.get("args", []))
    if op == "not":
        return not match_filter(node.get("arg", {}), scopes)

    scope = str(node.get("scope", ""))
    exists, actual = _get_path(scopes.get(scope, {}), list(node.get("path", [])))
    if op == "exists":
        return exists
    if not exists:
        return False
    expected = node.get("value")
    if op == "eq": return actual == expected
    if op == "ne": return actual != expected
    if op == "lt": return actual < expected
    if op == "le": return actual <= expected
    if op == "gt": return actual > expected
    if op == "ge": return actual >= expected
    if op == "in": return actual in expected
    if op == "contains":
        try:
            return expected in actual
        except TypeError:
            return False
    raise ValueError(f"unknown Midnight filter op: {op}")


class ScopeValues:
    __slots__ = ("_owner", "_scope")

    def __init__(self, owner: "ScopedMidnight", scope: str) -> None:
        object.__setattr__(self, "_owner", owner)
        object.__setattr__(self, "_scope", scope)

    def _data(self) -> dict[str, t.Any]:
        return self._owner.current_scopes[self._scope]

    def __getattr__(self, name: str) -> t.Any:
        if name.startswith("_"):
            raise AttributeError(name)
        return self._data().get(name)

    def __setattr__(self, name: str, value: t.Any) -> None:
        if name.startswith("_"):
            object.__setattr__(self, name, value)
        else:
            self._data()[name] = value

    def update(self, values: t.Mapping[str, t.Any] | None = None, **kwargs: t.Any) -> None:
        if values:
            self._data().update(values)
        self._data().update(kwargs)

    def as_dict(self) -> dict[str, t.Any]:
        return dict(self._data())


class ConnectionRecord:
    __slots__ = ("id", "tab_id", "scopes", "send")

    def __init__(
        self,
        connection_id: str,
        tab_id: str,
        scopes: dict[str, dict[str, t.Any]],
        send: t.Callable[[dict[str, t.Any]], t.Awaitable[None]],
    ) -> None:
        self.id = connection_id
        self.tab_id = tab_id
        self.scopes = scopes
        self.send = send


class Target:
    __slots__ = ("owner", "filter")

    def __init__(self, owner: "ScopedMidnight", filter: FilterExpr | None) -> None:
        self.owner = owner
        self.filter = filter

    async def _send(self, command: dict[str, t.Any]) -> int:
        return await self.owner._broadcast(self.filter, command)

    async def emit(self, name: str, detail: t.Any = None) -> int:
        return await self._send({"op": "emit", "name": str(name), "detail": detail})

    async def text(self, selector: str, value: t.Any) -> int:
        return await self._send({"op": "text", "selector": str(selector), "value": str(value)})

    async def html(self, selector: str, value: t.Any) -> int:
        return await self._send({"op": "html", "selector": str(selector), "value": str(value)})

    async def value(self, selector: str, value: t.Any) -> int:
        return await self._send({"op": "value", "selector": str(selector), "value": value})

    async def attr(self, selector: str, name: str, value: t.Any = None) -> int:
        return await self._send({"op": "attr", "selector": str(selector), "name": str(name), "value": value})

    async def add_class(self, selector: str, *names: str) -> int:
        return await self._send({"op": "class_add", "selector": str(selector), "names": [str(x) for x in names]})

    async def remove_class(self, selector: str, *names: str) -> int:
        return await self._send({"op": "class_remove", "selector": str(selector), "names": [str(x) for x in names]})

    async def focus(self, selector: str) -> int:
        return await self._send({"op": "focus", "selector": str(selector)})


class ScopedMidnight(CompiledMidnight):
    def __init__(self, *args: t.Any, **kwargs: t.Any) -> None:
        super().__init__(*args, **kwargs)
        self._connections: dict[str, ConnectionRecord] = {}
        self._tabs: dict[str, dict[str, t.Any]] = {}
        self._connection_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
            f"midnight_connection_{id(self)}", default=None
        )
        self.F = ScopeValues(self, "F")
        self.G = ScopeValues(self, "G")
        self.S = ScopeValues(self, "S")
        self.Q = ScopeValues(self, "Q")

    @property
    def current_connection(self) -> ConnectionRecord:
        key = self._connection_id.get()
        if key is None or key not in self._connections:
            raise RuntimeError("F/G/S/Q require an active Midnight WebSocket connection")
        return self._connections[key]

    @property
    def current_scopes(self) -> dict[str, dict[str, t.Any]]:
        return self.current_connection.scopes

    def to(self, filter: FilterExpr | None = None, **session_equals: t.Any) -> Target:
        expr = filter
        for key, value in session_equals.items():
            item = getattr(F, key) == value
            expr = item if expr is None else expr & item
        return Target(self, expr)

    @property
    def all(self) -> Target:
        return Target(self, None)

    def filter_json(self, filter: FilterExpr) -> dict[str, t.Any]:
        return _filter(filter).to_dict()

    def _register_connection(
        self,
        *,
        connection_id: str,
        tab_id: str,
        send: t.Callable[[dict[str, t.Any]], t.Awaitable[None]],
        F_values: t.Mapping[str, t.Any] | None = None,
        Q_values: t.Mapping[str, t.Any] | None = None,
    ) -> ConnectionRecord:
        g_values = self._tabs.setdefault(tab_id, {"id": tab_id})
        scopes = {
            "F": dict(F_values or {}),
            "G": g_values,
            "S": {"id": connection_id},
            "Q": dict(Q_values or {}),
        }
        record = ConnectionRecord(connection_id, tab_id, scopes, send)
        self._connections[connection_id] = record
        return record

    def _unregister_connection(self, connection_id: str) -> None:
        self._connections.pop(connection_id, None)

    @contextlib.contextmanager
    def connection(self, connection_id: str):
        token = self._connection_id.set(connection_id)
        try:
            yield self._connections[connection_id]
        finally:
            self._connection_id.reset(token)

    async def _broadcast(self, filter: FilterExpr | None, command: dict[str, t.Any]) -> int:
        node = None if filter is None else _filter(filter).node
        targets = [
            record
            for record in tuple(self._connections.values())
            if node is None or match_filter(node, record.scopes)
        ]
        for record in targets:
            await record.send({"type": "midnight-commands", "event_id": None, "commands": [dict(command)]})
        return len(targets)


class ScopedMidnightWebSocketAdapter(MidnightWebSocketAdapter):
    def __init__(self, midnight: ScopedMidnight) -> None:
        super().__init__(midnight)
        self.midnight = midnight

    async def serve(
        self,
        ws: t.Any,
        *,
        F: t.Mapping[str, t.Any] | None = None,
        Q: t.Mapping[str, t.Any] | None = None,
    ) -> None:
        connection_id = secrets.token_urlsafe(24)
        trusted_id = trusted_session_id(connection_id)
        tab_id: str | None = None

        async def send(message: dict[str, t.Any]) -> None:
            await ws.send_json(message)

        await ws.accept()
        await ws.send_json({"type": "midnight-config", "subscriptions": self.midnight.subscriptions()})
        try:
            while True:
                message = await ws.receive_json()
                if not isinstance(message, dict) or message.get("type") != "midnight-event":
                    await ws.send_json({"type": "midnight-error", "error": "expected midnight-event"})
                    continue
                payload = message.get("event")
                if not isinstance(payload, dict):
                    await ws.send_json({"type": "midnight-error", "error": "event must be an object"})
                    continue

                incoming_tab = str(message.get("tab_id") or "")
                if not incoming_tab:
                    incoming_tab = connection_id
                if tab_id is None:
                    tab_id = incoming_tab
                    self.midnight._register_connection(
                        connection_id=connection_id,
                        tab_id=tab_id,
                        send=send,
                        F_values=F,
                        Q_values=Q,
                    )

                with self.midnight.connection(connection_id):
                    commands = await self.midnight.dispatch_trusted(trusted_id, payload)
                await ws.send_json({
                    "type": "midnight-commands",
                    "event_id": message.get("event_id"),
                    "commands": commands,
                })
        except ConnectionError:
            return
        finally:
            self.midnight._unregister_connection(connection_id)
            self.midnight.drop_session(trusted_id)


__all__ = [
    "F", "G", "S", "Q",
    "FilterExpr", "FilterField", "FilterNamespace",
    "ScopeValues", "ScopedMidnight", "ScopedMidnightWebSocketAdapter",
    "Target", "match_filter",
]
