"""Midnight: Night's bidirectional Python/browser UI runtime.

Python-side Midnight, hybrid expressions, client compilation, and the direct
WebSocket adapter live here. The browser runtime lives in ``midnight.js``.
"""

from __future__ import annotations

import contextlib
import contextvars
import functools
import hashlib
import html as _html
import inspect
import json
import operator
from pathlib import Path
import re
import secrets
import sys
import time
import typing as t

from night import HTMLResponse, TemplateEngine

Handler = t.Callable[[dict[str, t.Any]], t.Any]
TrustedSessionId = t.NewType("TrustedSessionId", str)


def trusted_session_id(value: str) -> TrustedSessionId:
    return TrustedSessionId(str(value))


def _plain(value: t.Any) -> t.Any:
    to_py = getattr(value, "to_py", None)
    if callable(to_py):
        try:
            return to_py()
        except Exception:
            pass
    return value


class MidnightTemplateEngine(TemplateEngine):
    _bindable = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*")

    def render_value(self, expression, value, context, *, autoescape, options):
        rendered = super().render_value(
            expression, value, context, autoescape=autoescape, options=options
        )
        if not options.get("live") or not self._bindable.fullmatch(expression):
            return rendered
        name = _html.escape(expression, quote=True)
        return f'<span data-midnight-bind="{name}">{rendered}</span>'


class MidnightSession:
    def __init__(
        self,
        session_id: str,
        *,
        max_outbox: int = 256,
        clock: t.Callable[[], float] = time.monotonic,
    ) -> None:
        self.id = str(session_id)
        self.state: dict[str, t.Any] = {}
        self._outbox: list[dict[str, t.Any]] = []
        self.max_outbox = max(1, int(max_outbox))
        self._clock = clock
        self.last_used = self._clock()

    def touch(self) -> None:
        self.last_used = self._clock()

    def push(self, command: dict[str, t.Any]) -> None:
        self.touch()
        self._outbox.append(command)
        overflow = len(self._outbox) - self.max_outbox
        if overflow > 0:
            del self._outbox[:overflow]

    def drain(self) -> list[dict[str, t.Any]]:
        self.touch()
        queued, self._outbox = self._outbox, []
        return queued


class Midnight:
    DEFAULT_SESSION = "default"

    def __init__(
        self,
        *,
        max_sessions: int = 256,
        session_ttl: float = 300.0,
        max_outbox: int = 256,
        clock: t.Callable[[], float] = time.monotonic,
    ) -> None:
        self._handlers: dict[tuple[str, str | None], list[Handler]] = {}
        self._ws_handlers: dict[str, list[Handler]] = {}
        self._subscriptions: list[dict[str, t.Any]] = []
        self._subscription_keys: set[tuple[str, str | None, bool]] = set()
        self._sessions: dict[str, MidnightSession] = {}
        self.max_sessions = max(1, int(max_sessions))
        self.session_ttl = max(0.0, float(session_ttl))
        self.max_outbox = max(1, int(max_outbox))
        self._clock = clock
        self._session_id: contextvars.ContextVar[str] = contextvars.ContextVar(
            f"night_midnight_session_{id(self)}", default=self.DEFAULT_SESSION
        )
        self.templates = MidnightTemplateEngine()
        self._get_session(self.DEFAULT_SESSION)

    @property
    def session_id(self) -> str:
        return self._session_id.get()

    @property
    def current_session(self) -> MidnightSession:
        return self._get_session(self.session_id)

    @property
    def state(self) -> dict[str, t.Any]:
        return self.current_session.state

    def _prune_sessions(self, *, keep: str | None = None) -> None:
        now = self._clock()
        if self.session_ttl > 0:
            expired = [
                key
                for key, session in self._sessions.items()
                if key != self.DEFAULT_SESSION
                and key != keep
                and now - session.last_used > self.session_ttl
            ]
            for key in expired:
                self._sessions.pop(key, None)

        while len(self._sessions) >= self.max_sessions:
            candidates = [
                (session.last_used, key)
                for key, session in self._sessions.items()
                if key != self.DEFAULT_SESSION and key != keep
            ]
            if not candidates:
                break
            _, oldest = min(candidates)
            self._sessions.pop(oldest, None)

    def _get_session(self, key: str) -> MidnightSession:
        key = str(key)
        session = self._sessions.get(key)
        if session is None:
            self._prune_sessions(keep=key)
            session = MidnightSession(key, max_outbox=self.max_outbox, clock=self._clock)
            self._sessions[key] = session
        else:
            session.touch()
            self._prune_sessions(keep=key)
        return session

    def prune_sessions(self) -> int:
        before = len(self._sessions)
        self._prune_sessions(keep=self.session_id)
        return before - len(self._sessions)

    def get_session(self, session_id: TrustedSessionId | None = None) -> MidnightSession:
        key = self.session_id if session_id is None else str(session_id)
        return self._get_session(key)

    def session_ids(self) -> tuple[str, ...]:
        return tuple(self._sessions)

    @contextlib.contextmanager
    def trusted_session(self, session_id: TrustedSessionId):
        key = str(session_id)
        session = self._get_session(key)
        token = self._session_id.set(key)
        try:
            yield session
        finally:
            self._session_id.reset(token)

    def drop_session(self, session_id: TrustedSessionId) -> bool:
        key = str(session_id)
        removed = self._sessions.pop(key, None) is not None
        if key == self.DEFAULT_SESSION:
            self._get_session(self.DEFAULT_SESSION)
        return removed

    def on(
        self,
        event: str,
        selector: str | None = None,
        *,
        prevent_default: bool = False,
    ):
        event = str(event)
        selector = str(selector) if selector is not None else None

        def decorator(fn: Handler) -> Handler:
            self._handlers.setdefault((event, selector), []).append(fn)
            if not event.startswith("custom:"):
                key = (event, selector, bool(prevent_default))
                if key not in self._subscription_keys:
                    self._subscription_keys.add(key)
                    self._subscriptions.append(
                        {
                            "event": event,
                            "selector": selector,
                            "prevent_default": bool(prevent_default),
                        }
                    )
            return fn

        return decorator

    def on_event(self, name: str):
        return self.on(f"custom:{name}")

    def _on_lifecycle(self, name: str, fn: Handler | None = None):
        decorator = self.on_event(f"__lifecycle_{name}")
        return decorator if fn is None else decorator(fn)

    def on_hide(self, fn: Handler | None = None):
        return self._on_lifecycle("hide", fn)

    def on_show(self, fn: Handler | None = None):
        return self._on_lifecycle("show", fn)

    def on_leave(self, fn: Handler | None = None):
        return self._on_lifecycle("leave", fn)

    def on_ws(self, event: str):
        event = str(event)

        def decorator(fn: Handler) -> Handler:
            self._ws_handlers.setdefault(event, []).append(fn)
            return fn

        return decorator

    def subscriptions(self) -> list[dict[str, t.Any]]:
        return [dict(item) for item in self._subscriptions]

    def subscriptions_json(self) -> str:
        return json.dumps(self.subscriptions(), separators=(",", ":"))

    def _browser_push(self, command: dict[str, t.Any]) -> bool:
        try:
            from js import nightMidnightPush  # type: ignore
        except ImportError:
            return False
        return bool(nightMidnightPush(json.dumps(command, separators=(",", ":"), default=str)))

    def _push(self, op: str, **payload: t.Any) -> None:
        command = {"op": op, **payload}
        if not self._browser_push(command):
            self.current_session.push(command)

    def drain(self) -> list[dict[str, t.Any]]:
        return self.current_session.drain()

    def drain_json(self) -> str:
        return json.dumps(self.drain(), separators=(",", ":"), default=str)

    def emit(self, name: str, detail: t.Any = None) -> None:
        self._push("emit", name=str(name), detail=detail)

    def text(self, selector: str, value: t.Any) -> None:
        self._push("text", selector=str(selector), value=str(value))

    def html(self, selector: str, value: t.Any) -> None:
        self._push("html", selector=str(selector), value=str(value))

    def value(self, selector: str, value: t.Any) -> None:
        self._push("value", selector=str(selector), value=value)

    def attr(self, selector: str, name: str, value: t.Any = None) -> None:
        self._push("attr", selector=str(selector), name=str(name), value=value)

    def add_class(self, selector: str, *names: str) -> None:
        self._push("class_add", selector=str(selector), names=[str(x) for x in names])

    def remove_class(self, selector: str, *names: str) -> None:
        self._push("class_remove", selector=str(selector), names=[str(x) for x in names])

    def focus(self, selector: str) -> None:
        self._push("focus", selector=str(selector))

    def set(self, name: str, value: t.Any) -> None:
        key = str(name)
        self.state[key] = value
        self._push("bind", name=key, value=value)

    def persist(
        self,
        url: str,
        data: t.Any = None,
        *,
        key: str = "default",
        transport: str = "auto",
        when: str = "leave",
        headers: dict[str, str] | None = None,
        content_type: str = "application/json",
    ) -> None:
        transport = str(transport).lower()
        when = str(when).lower()
        if transport not in {"auto", "beacon", "fetch"}:
            raise ValueError("transport must be 'auto', 'beacon', or 'fetch'")
        if when not in {"leave", "hide", "now"}:
            raise ValueError("when must be 'leave', 'hide', or 'now'")
        normalized_headers = {str(k): str(v) for k, v in (headers or {}).items()}
        if transport == "beacon" and normalized_headers:
            raise ValueError("Beacon transport cannot set custom request headers")
        self._push(
            "persist",
            url=str(url),
            data=data,
            key=str(key),
            transport=transport,
            when=when,
            headers=normalized_headers,
            content_type=str(content_type),
        )

    def cancel_persist(self, key: str = "default") -> None:
        self._push("persist_cancel", key=str(key))

    def flush_persist(self, key: str | None = None) -> None:
        self._push("persist_flush", key=None if key is None else str(key))

    def render_template_string(self, source: str, **context: t.Any) -> HTMLResponse:
        data = {**self.state, **context}
        html = self.templates.render_text(source, data, autoescape=True, render_options={"live": True})
        return HTMLResponse(html)

    def render_template(self, filename: str, **context: t.Any) -> HTMLResponse:
        data = {**self.state, **context}
        html = self.templates.render_file(filename, data, autoescape=True, render_options={"live": True})
        return HTMLResponse(html)

    def ws_connect(
        self,
        url: str,
        *,
        socket_id: str = "default",
        protocols: list[str] | None = None,
        reconnect: bool = True,
        reconnect_delay: float = 0.5,
        reconnect_max_delay: float = 5.0,
    ) -> None:
        reconnect_delay = float(reconnect_delay)
        reconnect_max_delay = float(reconnect_max_delay)
        if reconnect_delay < 0 or reconnect_max_delay < 0:
            raise ValueError("WebSocket reconnect delays must be >= 0")
        if reconnect_max_delay < reconnect_delay:
            raise ValueError("reconnect_max_delay must be >= reconnect_delay")
        self._push(
            "ws_connect",
            url=str(url),
            socket_id=str(socket_id),
            protocols=list(protocols or []),
            reconnect=bool(reconnect),
            reconnect_delay_ms=int(reconnect_delay * 1000),
            reconnect_max_delay_ms=int(reconnect_max_delay * 1000),
        )

    def ws_send(self, data: t.Any, *, socket_id: str = "default") -> None:
        self._push("ws_send", socket_id=str(socket_id), data=data)

    def ws_close(
        self,
        *,
        socket_id: str = "default",
        code: int = 1000,
        reason: str = "",
    ) -> None:
        self._push("ws_close", socket_id=str(socket_id), code=int(code), reason=str(reason))

    async def _run_handlers(self, handlers: list[Handler], payload: dict[str, t.Any]) -> None:
        for handler in handlers:
            result = handler(payload)
            if inspect.isawaitable(result):
                await result
            if isinstance(result, dict) and "op" in result:
                self.current_session.push(dict(result))
            elif isinstance(result, (list, tuple)):
                for item in result:
                    if isinstance(item, dict) and "op" in item:
                        self.current_session.push(dict(item))

    async def _dispatch_current(self, payload: dict[str, t.Any]) -> list[dict[str, t.Any]]:
        payload = dict(_plain(payload) or {})
        event = str(payload.get("type", ""))
        selector = payload.get("selector")
        handlers = list(self._handlers.get((event, selector), ()))
        if selector is not None:
            handlers.extend(self._handlers.get((event, None), ()))
        await self._run_handlers(handlers, payload)
        return self.drain()

    async def dispatch_untrusted(self, payload: dict[str, t.Any]) -> list[dict[str, t.Any]]:
        return await self._dispatch_current(payload)

    dispatch = dispatch_untrusted

    async def dispatch_trusted(
        self,
        session_id: TrustedSessionId,
        payload: dict[str, t.Any],
    ) -> list[dict[str, t.Any]]:
        with self.trusted_session(session_id):
            return await self._dispatch_current(payload)

    async def _dispatch_ws_current(self, payload: dict[str, t.Any]) -> list[dict[str, t.Any]]:
        payload = dict(_plain(payload) or {})
        event = str(payload.get("type", ""))
        await self._run_handlers(list(self._ws_handlers.get(event, ())), payload)
        return self.drain()

    async def dispatch_ws_untrusted(self, payload: dict[str, t.Any]) -> list[dict[str, t.Any]]:
        return await self._dispatch_ws_current(payload)

    dispatch_ws = dispatch_ws_untrusted

    async def dispatch_ws_trusted(
        self,
        session_id: TrustedSessionId,
        payload: dict[str, t.Any],
    ) -> list[dict[str, t.Any]]:
        with self.trusted_session(session_id):
            return await self._dispatch_ws_current(payload)

    async def dispatch_json(self, payload: str) -> str:
        commands = await self.dispatch_untrusted(json.loads(str(payload)))
        return json.dumps(commands, separators=(",", ":"), default=str)

    async def dispatch_json_trusted(self, session_id: TrustedSessionId, payload: str) -> str:
        commands = await self.dispatch_trusted(session_id, json.loads(str(payload)))
        return json.dumps(commands, separators=(",", ":"), default=str)

    async def dispatch_ws_json(self, payload: str) -> str:
        commands = await self.dispatch_ws_untrusted(json.loads(str(payload)))
        return json.dumps(commands, separators=(",", ":"), default=str)

    async def dispatch_ws_json_trusted(self, session_id: TrustedSessionId, payload: str) -> str:
        commands = await self.dispatch_ws_trusted(session_id, json.loads(str(payload)))
        return json.dumps(commands, separators=(",", ":"), default=str)


class HybridExpressionError(RuntimeError):
    pass


class _ServerExpr:
    __slots__ = ("node",)

    def __init__(self, node: tuple[t.Any, ...]) -> None:
        self.node = node

    def _binary(self, op: str, other: t.Any) -> "_ServerExpr":
        return _ServerExpr(("binary", op, self, other))

    def _rbinary(self, op: str, other: t.Any) -> "_ServerExpr":
        return _ServerExpr(("binary", op, other, self))

    def __add__(self, other): return self._binary("add", other)
    def __radd__(self, other): return self._rbinary("add", other)
    def __sub__(self, other): return self._binary("sub", other)
    def __rsub__(self, other): return self._rbinary("sub", other)
    def __mul__(self, other): return self._binary("mul", other)
    def __rmul__(self, other): return self._rbinary("mul", other)
    def __truediv__(self, other): return self._binary("truediv", other)
    def __rtruediv__(self, other): return self._rbinary("truediv", other)
    def __floordiv__(self, other): return self._binary("floordiv", other)
    def __rfloordiv__(self, other): return self._rbinary("floordiv", other)
    def __mod__(self, other): return self._binary("mod", other)
    def __rmod__(self, other): return self._rbinary("mod", other)
    def __pow__(self, other): return self._binary("pow", other)
    def __rpow__(self, other): return self._rbinary("pow", other)


class DOMValue(_ServerExpr):
    __slots__ = ("owner", "selector", "property")

    def __init__(self, owner: "HybridMidnight", selector: str, property: str) -> None:
        self.owner = owner
        self.selector = str(selector)
        self.property = str(property)
        super().__init__(("dom", self.selector, self.property))


class ClientExpr:
    __slots__ = ("node",)

    def __init__(self, node: dict[str, t.Any]) -> None:
        self.node = node

    def _binary(self, op: str, other: t.Any) -> "ClientExpr":
        return ClientExpr({"kind": "binary", "op": op, "left": self.node, "right": _client_node(other)})

    def _rbinary(self, op: str, other: t.Any) -> "ClientExpr":
        return ClientExpr({"kind": "binary", "op": op, "left": _client_node(other), "right": self.node})

    def __add__(self, other): return self._binary("add", other)
    def __radd__(self, other): return self._rbinary("add", other)
    def __sub__(self, other): return self._binary("sub", other)
    def __rsub__(self, other): return self._rbinary("sub", other)
    def __mul__(self, other): return self._binary("mul", other)
    def __rmul__(self, other): return self._rbinary("mul", other)
    def __truediv__(self, other): return self._binary("div", other)
    def __rtruediv__(self, other): return self._rbinary("div", other)
    def __mod__(self, other): return self._binary("mod", other)
    def __rmod__(self, other): return self._rbinary("mod", other)
    def __pow__(self, other): return self._binary("pow", other)
    def __rpow__(self, other): return self._rbinary("pow", other)


class JSRef(ClientExpr):
    __slots__ = ("path",)

    def __init__(self, path: tuple[str, ...]) -> None:
        self.path = path
        super().__init__({"kind": "js_ref", "path": list(path)})

    def __getattr__(self, name: str) -> "JSRef":
        if name.startswith("_"):
            raise AttributeError(name)
        return JSRef((*self.path, name))

    def __call__(self, *args: t.Any) -> ClientExpr:
        return ClientExpr({"kind": "call", "callee": self.node, "args": [_client_node(arg) for arg in args]})


js = JSRef(())


def _client_node(value: t.Any) -> dict[str, t.Any]:
    if isinstance(value, ClientExpr):
        return value.node
    if isinstance(value, DOMValue):
        return {"kind": "dom", "selector": value.selector, "property": value.property}
    if isinstance(value, _ServerExpr):
        raise HybridExpressionError("server/Python expressions cannot be embedded inside js expressions")
    if isinstance(value, (str, int, float, bool)) or value is None:
        return {"kind": "literal", "value": value}
    if isinstance(value, (list, tuple)):
        return {"kind": "literal", "value": list(value)}
    if isinstance(value, dict):
        return {"kind": "literal", "value": dict(value)}
    raise HybridExpressionError(f"{type(value).__name__} is not serializable into a client expression")


class DOMRef:
    __slots__ = ("_owner", "_selector")

    def __init__(self, owner: "HybridMidnight", selector: str) -> None:
        object.__setattr__(self, "_owner", owner)
        object.__setattr__(self, "_selector", str(selector))

    @property
    def selector(self) -> str:
        return self._selector

    def __getattr__(self, name: str) -> DOMValue:
        if name.startswith("_"):
            raise AttributeError(name)
        return DOMValue(self._owner, self._selector, name)

    def __setattr__(self, name: str, value: t.Any) -> None:
        if name.startswith("_"):
            object.__setattr__(self, name, value)
            return
        if isinstance(value, ClientExpr):
            self._owner._push("hybrid_client_set", selector=self._selector, property=str(name), expr=value.node)
            return
        if isinstance(value, _ServerExpr):
            self._owner._queue_server_set(self._selector, str(name), value)
            return
        self._owner._push("dom_set", selector=self._selector, property=str(name), value=value)


_SERVER_BINARY: dict[str, t.Callable[[t.Any, t.Any], t.Any]] = {
    "add": operator.add,
    "sub": operator.sub,
    "mul": operator.mul,
    "truediv": operator.truediv,
    "floordiv": operator.floordiv,
    "mod": operator.mod,
    "pow": operator.pow,
}


def _compile_server(value: t.Any, reads: list[dict[str, str]]) -> tuple[t.Any, ...]:
    if isinstance(value, DOMValue):
        index = len(reads)
        reads.append({"selector": value.selector, "property": value.property})
        return ("input", index)
    if isinstance(value, _ServerExpr):
        kind, *parts = value.node
        if kind == "binary":
            op, left, right = parts
            return ("binary", op, _compile_server(left, reads), _compile_server(right, reads))
        if kind == "dom":
            selector, prop = parts
            index = len(reads)
            reads.append({"selector": str(selector), "property": str(prop)})
            return ("input", index)
        raise HybridExpressionError(f"unknown server expression node: {kind}")
    if isinstance(value, ClientExpr):
        raise HybridExpressionError("js/client expressions must stay entirely client-side")
    return ("literal", value)


def _eval_server(plan: tuple[t.Any, ...], values: list[t.Any]) -> t.Any:
    kind = plan[0]
    if kind == "literal":
        return plan[1]
    if kind == "input":
        return values[int(plan[1])]
    if kind == "binary":
        op = str(plan[1])
        fn = _SERVER_BINARY.get(op)
        if fn is None:
            raise HybridExpressionError(f"unsupported Python operation: {op}")
        return fn(_eval_server(plan[2], values), _eval_server(plan[3], values))
    raise HybridExpressionError(f"unknown server plan node: {kind}")


class HybridMidnight(Midnight):
    def __init__(self, *args: t.Any, **kwargs: t.Any) -> None:
        super().__init__(*args, **kwargs)
        self._hybrid_pending: dict[tuple[str, int], tuple[str, str, tuple[t.Any, ...]]] = {}
        self._hybrid_sequence = 0

    def get(self, selector: str) -> DOMRef:
        return DOMRef(self, selector)

    def _queue_server_set(self, selector: str, property: str, expr: _ServerExpr) -> None:
        reads: list[dict[str, str]] = []
        plan = _compile_server(expr, reads)
        self._hybrid_sequence += 1
        request_id = self._hybrid_sequence
        self._hybrid_pending[(self.session_id, request_id)] = (str(selector), str(property), plan)
        self._push("hybrid_server_set", request_id=request_id, reads=reads)

    def _resolve_hybrid_result(self, payload: dict[str, t.Any]) -> None:
        detail = payload.get("detail") if isinstance(payload, dict) else None
        if not isinstance(detail, dict):
            return
        try:
            request_id = int(detail.get("request_id"))
        except (TypeError, ValueError):
            return
        pending = self._hybrid_pending.pop((self.session_id, request_id), None)
        if pending is None:
            return
        selector, prop, plan = pending
        values = detail.get("values")
        if not isinstance(values, list):
            values = []
        try:
            result = _eval_server(plan, values)
        except Exception as exc:
            self._push("hybrid_error", request_id=request_id, error_type=type(exc).__name__, message=str(exc))
            return
        self._push("dom_set", selector=selector, property=prop, value=result)

    async def _dispatch_current(self, payload: dict[str, t.Any]) -> list[dict[str, t.Any]]:
        if isinstance(payload, dict) and str(payload.get("type", "")) == "custom:__hybrid_result":
            self._resolve_hybrid_result(payload)
            return self.drain()
        return await super()._dispatch_current(payload)


class MidnightCompileError(HybridExpressionError):
    pass


class EventExpr(ClientExpr):
    __slots__ = ("path",)

    def __init__(self, path: tuple[str, ...] = ()) -> None:
        self.path = path
        super().__init__({"kind": "event", "path": list(path)})

    def __getitem__(self, key: str) -> "EventExpr":
        return EventExpr((*self.path, str(key)))

    def get(self, key: str, default: t.Any = None) -> ClientExpr:
        return ClientExpr({"kind": "event_get", "path": [*self.path, str(key)], "default": default})

    def __getattr__(self, name: str) -> "EventExpr":
        if name.startswith("_"):
            raise AttributeError(name)
        return EventExpr((*self.path, name))


class CompiledMidnight(HybridMidnight):
    def __init__(self, *args: t.Any, **kwargs: t.Any) -> None:
        super().__init__(*args, **kwargs)
        self._compile_program: list[dict[str, t.Any]] | None = None

    def on(self, event: str, selector: str | None = None, *, prevent_default: bool = False):
        base = super().on(event, selector, prevent_default=prevent_default)

        def decorator(fn):
            spec = getattr(fn, "__midnight_compile_spec__", None)
            if isinstance(spec, dict):
                spec["event"] = str(event)
                spec["selector"] = None if selector is None else str(selector)
                spec["prevent_default"] = bool(prevent_default)
            return base(fn)

        return decorator

    def _push(self, op: str, **payload: t.Any) -> None:
        program = self._compile_program
        if program is None:
            return super()._push(op, **payload)
        if op == "hybrid_client_set":
            program.append({
                "op": "dom_set_expr",
                "selector": str(payload["selector"]),
                "property": str(payload["property"]),
                "expr": payload["expr"],
            })
            return
        if op == "dom_set":
            program.append({
                "op": "dom_set",
                "selector": str(payload["selector"]),
                "property": str(payload["property"]),
                "value": payload.get("value"),
            })
            return
        raise MidnightCompileError(f"{op!r} requires server execution and cannot be used inside @midnight.compile")

    def _handler_id(self, fn: t.Callable[..., t.Any]) -> str:
        code = getattr(fn, "__code__", None)
        raw = (
            f"{getattr(fn, '__module__', '')}:{getattr(fn, '__qualname__', repr(fn))}:"
            f"{getattr(code, 'co_code', b'')!r}:{getattr(code, 'co_consts', ())!r}"
        ).encode("utf-8", "replace")
        return hashlib.sha256(raw).hexdigest()[:20]

    def _compiled_handlers_for_current_session(self) -> set[str]:
        session = self.current_session
        installed = getattr(session, "_midnight_compiled_handlers", None)
        if installed is None:
            installed = set()
            setattr(session, "_midnight_compiled_handlers", installed)
        return installed

    def _compiled_pair_is_exclusive(self, event: str, selector: str | None) -> bool:
        handlers = list(self._handlers.get((event, selector), ()))
        if selector is not None:
            handlers.extend(self._handlers.get((event, None), ()))
        return bool(handlers) and all(
            isinstance(getattr(handler, "__midnight_compile_spec__", None), dict)
            for handler in handlers
        )

    def compile(self, fn: t.Callable[..., t.Any] | None = None):
        def decorate(func: t.Callable[..., t.Any]):
            spec: dict[str, t.Any] = {
                "id": self._handler_id(func),
                "event": None,
                "selector": None,
                "prevent_default": False,
            }

            @functools.wraps(func)
            def wrapper(event: t.Any = None, *args: t.Any, **kwargs: t.Any):
                installed = self._compiled_handlers_for_current_session()
                if spec["id"] in installed:
                    return None
                if self._compile_program is not None:
                    raise MidnightCompileError("nested @midnight.compile tracing is not supported")
                if spec["event"] is None:
                    raise MidnightCompileError("@midnight.compile must be registered with @midnight.on")

                program: list[dict[str, t.Any]] = []
                self._compile_program = program
                try:
                    result = func(EventExpr(), *args, **kwargs)
                    if inspect.isawaitable(result):
                        raise MidnightCompileError("async compiled handlers are not supported yet")
                finally:
                    self._compile_program = None

                if not program:
                    raise MidnightCompileError("compiled handler produced no client-side commands")

                installed.add(spec["id"])
                super(CompiledMidnight, self)._push(
                    "compiled_install",
                    handler_id=spec["id"],
                    event=spec["event"],
                    selector=spec["selector"],
                    prevent_default=spec["prevent_default"],
                    exclusive=self._compiled_pair_is_exclusive(spec["event"], spec["selector"]),
                    program=program,
                    execute_now=True,
                )
                return None

            wrapper.__midnight_compile_spec__ = spec
            return wrapper

        return decorate if fn is None else decorate(fn)


class MidnightWebSocketAdapter:
    """Serve one Midnight instance over a Night WebSocket route."""

    def __init__(self, midnight: Midnight) -> None:
        self.midnight = midnight

    async def serve(self, ws: t.Any) -> None:
        session_id = trusted_session_id(secrets.token_urlsafe(24))
        await ws.accept()
        await ws.send_json(
            {
                "type": "midnight-config",
                "subscriptions": self.midnight.subscriptions(),
            }
        )
        try:
            while True:
                message = await ws.receive_json()
                if not isinstance(message, dict) or message.get("type") != "midnight-event":
                    await ws.send_json(
                        {
                            "type": "midnight-error",
                            "error": "expected midnight-event",
                        }
                    )
                    continue
                payload = message.get("event")
                if not isinstance(payload, dict):
                    await ws.send_json(
                        {
                            "type": "midnight-error",
                            "error": "event must be an object",
                        }
                    )
                    continue
                commands = await self.midnight.dispatch_trusted(session_id, payload)
                await ws.send_json(
                    {
                        "type": "midnight-commands",
                        "event_id": message.get("event_id"),
                        "commands": commands,
                    }
                )
        except ConnectionError:
            return
        finally:
            self.midnight.drop_session(session_id)


async def serve_midnight_ws(midnight: Midnight, ws: t.Any) -> None:
    await MidnightWebSocketAdapter(midnight).serve(ws)


def midnight_js_path() -> Path:
    """Return the installed/source path to Midnight's browser runtime."""
    candidates = (
        Path(__file__).with_name("midnight.js"),
        Path(sys.prefix) / "midnight.js",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("midnight.js is not installed next to Night or in the environment prefix")


def read_midnight_js(*, encoding: str = "utf-8") -> str:
    return midnight_js_path().read_text(encoding=encoding)


def get(selector: str, *, midnight: HybridMidnight | None = None) -> DOMRef:
    if midnight is None:
        raise RuntimeError("get() needs midnight=...; prefer midnight.get(selector)")
    return midnight.get(selector)


_default_midnight: Midnight | None = None


def get_default_midnight() -> Midnight:
    global _default_midnight
    if _default_midnight is None:
        _default_midnight = Midnight()
    return _default_midnight


def reset_default_midnight() -> Midnight:
    global _default_midnight
    _default_midnight = Midnight()
    return _default_midnight


class _DefaultMidnightProxy:
    __slots__ = ()

    def __getattr__(self, name: str) -> t.Any:
        return getattr(get_default_midnight(), name)

    def __repr__(self) -> str:
        if _default_midnight is None:
            return "<midnight lazy>"
        return repr(_default_midnight)


midnight: Midnight = t.cast(Midnight, _DefaultMidnightProxy())

__all__ = [
    "ClientExpr",
    "CompiledMidnight",
    "DOMRef",
    "DOMValue",
    "EventExpr",
    "HybridExpressionError",
    "HybridMidnight",
    "JSRef",
    "Midnight",
    "MidnightCompileError",
    "MidnightSession",
    "MidnightTemplateEngine",
    "MidnightWebSocketAdapter",
    "TrustedSessionId",
    "get",
    "get_default_midnight",
    "js",
    "midnight",
    "midnight_js_path",
    "read_midnight_js",
    "reset_default_midnight",
    "serve_midnight_ws",
    "trusted_session_id",
]
