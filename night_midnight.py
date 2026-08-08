"""Midnight: Browser Night's bidirectional Python/HTML bridge.

Midnight keeps the Python side runtime-independent. In Browser Night it can
push commands directly through Pyodide's ``js`` module; elsewhere commands are
queued and can be drained by an adapter.
"""

from __future__ import annotations

import contextlib
import contextvars
import html as _html
import inspect
import time
import re
import json
import typing as t

from night import HTMLResponse, TemplateEngine

Handler = t.Callable[[dict[str, t.Any]], t.Any]
TrustedSessionId = t.NewType("TrustedSessionId", str)


def trusted_session_id(value: str) -> TrustedSessionId:
    """Explicitly mark an adapter-derived identifier as trusted.

    This function does not authenticate input. Its purpose is to make the trust
    elevation visible at the adapter boundary and to give type checkers a
    distinct type for APIs that may address another client's session.
    """
    return TrustedSessionId(str(value))


def _plain(value: t.Any) -> t.Any:
    """Convert a Pyodide JsProxy-ish value into ordinary Python containers."""
    to_py = getattr(value, "to_py", None)
    if callable(to_py):
        try:
            return to_py()
        except Exception:
            pass
    return value


class MidnightTemplateEngine(TemplateEngine):
    """TemplateEngine extension that turns simple expressions into live bindings."""

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
    """Per-client Midnight state.

    Handlers and subscriptions live on :class:`Midnight`; mutable UI state and
    queued Python->HTML commands live here so concurrent users cannot consume or
    overwrite each other's data.
    """

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
        """ID of the Midnight session bound to the current async context."""
        return self._session_id.get()

    @property
    def current_session(self) -> MidnightSession:
        return self._get_session(self.session_id)

    @property
    def state(self) -> dict[str, t.Any]:
        """State for the current session.

        Existing ``midnight.state`` code therefore stays session-aware without
        requiring callers to index a shared dictionary manually.
        """
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
            session = MidnightSession(
                key, max_outbox=self.max_outbox, clock=self._clock
            )
            self._sessions[key] = session
        else:
            session.touch()
            self._prune_sessions(keep=key)
        return session

    def prune_sessions(self) -> int:
        """Drop expired/excess non-default sessions and return how many were removed."""
        before = len(self._sessions)
        self._prune_sessions(keep=self.session_id)
        return before - len(self._sessions)

    def get_session(
        self, session_id: TrustedSessionId | None = None
    ) -> MidnightSession:
        """Return the current session or an explicitly trusted session."""
        key = self.session_id if session_id is None else str(session_id)
        return self._get_session(key)

    def session_ids(self) -> tuple[str, ...]:
        return tuple(self._sessions)

    @contextlib.contextmanager
    def trusted_session(self, session_id: TrustedSessionId):
        """Bind operations to one adapter-authenticated client/session.

        ``ContextVar`` keeps the binding isolated across concurrent asyncio
        tasks and restores the previous session when the context exits. Callers
        should create ``TrustedSessionId`` only from authenticated connection or
        server-side session context, never directly from client payload data.
        """
        key = str(session_id)
        session = self._get_session(key)
        token = self._session_id.set(key)
        try:
            yield session
        finally:
            self._session_id.reset(token)

    def drop_session(self, session_id: TrustedSessionId) -> bool:
        """Forget one trusted server-side session and its queued state."""
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
        """Handle a DOM or custom event.

        DOM example::

            @midnight.on("click", "#save")
            def save(event): ...

        Custom HTML->Python events use ``custom:<name>`` or ``on_event``.
        """
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
        """Handle the page becoming hidden (best effort)."""
        return self._on_lifecycle("hide", fn)

    def on_show(self, fn: Handler | None = None):
        """Handle the page becoming visible again (best effort)."""
        return self._on_lifecycle("show", fn)

    def on_leave(self, fn: Handler | None = None):
        """Handle ``pagehide`` before navigation/unload (best effort).

        Do not rely on this hook to finish an async save during teardown. Use
        :meth:`persist` to pre-register data for Beacon/keepalive delivery.
        """
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

        return bool(
            nightMidnightPush(
                json.dumps(command, separators=(",", ":"), default=str)
            )
        )

    def _push(self, op: str, **payload: t.Any) -> None:
        command = {"op": op, **payload}
        if not self._browser_push(command):
            self.current_session.push(command)

    def drain(self) -> list[dict[str, t.Any]]:
        return self.current_session.drain()

    def drain_json(self) -> str:
        return json.dumps(self.drain(), separators=(",", ":"), default=str)

    # Python -> HTML -----------------------------------------------------
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
        """Update a live template binding in the current session."""
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
        """Pre-register a small payload for reliable page-lifecycle delivery.

        ``transport='auto'`` prefers ``navigator.sendBeacon`` when custom
        headers are not required and falls back to ``fetch(..., keepalive=True)``.
        ``when`` may be ``leave``, ``hide`` or ``now``. Reusing ``key`` replaces
        the previously registered payload.
        """
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
        """Remove a previously registered lifecycle payload."""
        self._push("persist_cancel", key=str(key))

    def flush_persist(self, key: str | None = None) -> None:
        """Ask the browser to send registered persistence data immediately."""
        self._push("persist_flush", key=None if key is None else str(key))

    def render_template_string(self, source: str, **context: t.Any) -> HTMLResponse:
        data = {**self.state, **context}
        html = self.templates.render_text(
            source, data, autoescape=True, render_options={"live": True}
        )
        return HTMLResponse(html)

    def render_template(self, filename: str, **context: t.Any) -> HTMLResponse:
        data = {**self.state, **context}
        html = self.templates.render_file(
            filename, data, autoescape=True, render_options={"live": True}
        )
        return HTMLResponse(html)

    # WebSocket transport ------------------------------------------------
    def ws_connect(
        self,
        url: str,
        *,
        socket_id: str = "default",
        protocols: list[str] | None = None,
    ) -> None:
        self._push(
            "ws_connect",
            url=str(url),
            socket_id=str(socket_id),
            protocols=list(protocols or []),
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
        self._push(
            "ws_close",
            socket_id=str(socket_id),
            code=int(code),
            reason=str(reason),
        )

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
        """Dispatch browser/client payload only within the current session.

        This method deliberately has no ``session_id`` parameter, so client data
        cannot choose another server-side Midnight session through this API.
        Browser Night normally uses the default per-runtime session here.
        """
        return await self._dispatch_current(payload)

    dispatch = dispatch_untrusted

    async def dispatch_trusted(
        self,
        session_id: TrustedSessionId,
        payload: dict[str, t.Any],
    ) -> list[dict[str, t.Any]]:
        """Dispatch payload into an adapter-authenticated server-side session."""
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

    async def dispatch_ws_json_trusted(
        self, session_id: TrustedSessionId, payload: str
    ) -> str:
        commands = await self.dispatch_ws_trusted(session_id, json.loads(str(payload)))
        return json.dumps(commands, separators=(",", ":"), default=str)


_default_midnight: Midnight | None = None


def get_default_midnight() -> Midnight:
    """Return the lazily-created convenience Midnight instance."""
    global _default_midnight
    if _default_midnight is None:
        _default_midnight = Midnight()
    return _default_midnight


def reset_default_midnight() -> Midnight:
    """Replace the convenience instance, primarily for tests/dev reloads."""
    global _default_midnight
    _default_midnight = Midnight()
    return _default_midnight


class _DefaultMidnightProxy:
    """Lazy compatibility proxy for ``from night_midnight import midnight``."""

    __slots__ = ()

    def __getattr__(self, name: str) -> t.Any:
        return getattr(get_default_midnight(), name)

    def __repr__(self) -> str:
        if _default_midnight is None:
            return "<midnight lazy>"
        return repr(_default_midnight)


midnight: Midnight = t.cast(Midnight, _DefaultMidnightProxy())

__all__ = [
    "Midnight",
    "MidnightSession",
    "MidnightTemplateEngine",
    "TrustedSessionId",
    "trusted_session_id",
    "get_default_midnight",
    "reset_default_midnight",
    "midnight",
]
