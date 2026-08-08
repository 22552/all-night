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
import re
import json
import typing as t

from night import HTMLResponse, TemplateEngine

Handler = t.Callable[[dict[str, t.Any]], t.Any]


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

    def __init__(self, session_id: str) -> None:
        self.id = str(session_id)
        self.state: dict[str, t.Any] = {}
        self._outbox: list[dict[str, t.Any]] = []

    def push(self, command: dict[str, t.Any]) -> None:
        self._outbox.append(command)

    def drain(self) -> list[dict[str, t.Any]]:
        queued, self._outbox = self._outbox, []
        return queued


class Midnight:
    DEFAULT_SESSION = "default"

    def __init__(self) -> None:
        self._handlers: dict[tuple[str, str | None], list[Handler]] = {}
        self._ws_handlers: dict[str, list[Handler]] = {}
        self._subscriptions: list[dict[str, t.Any]] = []
        self._sessions: dict[str, MidnightSession] = {}
        self._session_id: contextvars.ContextVar[str] = contextvars.ContextVar(
            f"night_midnight_session_{id(self)}", default=self.DEFAULT_SESSION
        )
        self.templates = MidnightTemplateEngine()
        self.get_session(self.DEFAULT_SESSION)

    @property
    def session_id(self) -> str:
        """ID of the Midnight session bound to the current async context."""
        return self._session_id.get()

    @property
    def current_session(self) -> MidnightSession:
        return self.get_session(self.session_id)

    @property
    def state(self) -> dict[str, t.Any]:
        """State for the current session.

        Existing ``midnight.state`` code therefore stays session-aware without
        requiring callers to index a shared dictionary manually.
        """
        return self.current_session.state

    def get_session(self, session_id: str | None = None) -> MidnightSession:
        key = self.session_id if session_id is None else str(session_id)
        session = self._sessions.get(key)
        if session is None:
            session = MidnightSession(key)
            self._sessions[key] = session
        return session

    def session_ids(self) -> tuple[str, ...]:
        return tuple(self._sessions)

    @contextlib.contextmanager
    def session(self, session_id: str):
        """Temporarily bind Midnight operations to one client/session.

        ``ContextVar`` keeps this binding isolated across concurrent asyncio
        tasks and restores the previous session when the context exits.
        """
        key = str(session_id)
        session = self.get_session(key)
        token = self._session_id.set(key)
        try:
            yield session
        finally:
            self._session_id.reset(token)

    session_scope = session

    def drop_session(self, session_id: str) -> bool:
        """Forget one server-side session and its queued commands/state."""
        key = str(session_id)
        removed = self._sessions.pop(key, None) is not None
        if key == self.DEFAULT_SESSION:
            self.get_session(self.DEFAULT_SESSION)
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
                item = {
                    "event": event,
                    "selector": selector,
                    "prevent_default": bool(prevent_default),
                }
                if item not in self._subscriptions:
                    self._subscriptions.append(item)
            return fn

        return decorator

    def on_event(self, name: str):
        return self.on(f"custom:{name}")

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

            return bool(
                nightMidnightPush(
                    json.dumps(command, separators=(",", ":"), default=str)
                )
            )
        except Exception:
            return False

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

    async def dispatch(
        self,
        payload: dict[str, t.Any],
        *,
        session_id: str | None = None,
    ) -> list[dict[str, t.Any]]:
        """Dispatch one HTML event, optionally scoped to a server-side client.

        A server adapter should derive ``session_id`` from its trusted
        connection/session context instead of accepting an arbitrary client
        supplied value.
        """
        if session_id is None:
            return await self._dispatch_current(payload)
        with self.session(session_id):
            return await self._dispatch_current(payload)

    async def _dispatch_ws_current(self, payload: dict[str, t.Any]) -> list[dict[str, t.Any]]:
        payload = dict(_plain(payload) or {})
        event = str(payload.get("type", ""))
        await self._run_handlers(list(self._ws_handlers.get(event, ())), payload)
        return self.drain()

    async def dispatch_ws(
        self,
        payload: dict[str, t.Any],
        *,
        session_id: str | None = None,
    ) -> list[dict[str, t.Any]]:
        if session_id is None:
            return await self._dispatch_ws_current(payload)
        with self.session(session_id):
            return await self._dispatch_ws_current(payload)

    async def dispatch_json(self, payload: str, *, session_id: str | None = None) -> str:
        commands = await self.dispatch(json.loads(str(payload)), session_id=session_id)
        return json.dumps(commands, separators=(",", ":"), default=str)

    async def dispatch_ws_json(self, payload: str, *, session_id: str | None = None) -> str:
        commands = await self.dispatch_ws(json.loads(str(payload)), session_id=session_id)
        return json.dumps(commands, separators=(",", ":"), default=str)


midnight = Midnight()

__all__ = ["Midnight", "MidnightSession", "MidnightTemplateEngine", "midnight"]
