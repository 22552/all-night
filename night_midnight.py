"""Midnight: Browser Night's bidirectional Python/HTML bridge.

Midnight keeps the Python side runtime-independent. In Browser Night it can
push commands directly through Pyodide's ``js`` module; elsewhere commands are
queued and can be drained by an adapter.
"""

from __future__ import annotations

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


class Midnight:
    def __init__(self) -> None:
        self._handlers: dict[tuple[str, str | None], list[Handler]] = {}
        self._ws_handlers: dict[str, list[Handler]] = {}
        self._subscriptions: list[dict[str, t.Any]] = []
        self._outbox: list[dict[str, t.Any]] = []
        self.state: dict[str, t.Any] = {}
        self.templates = MidnightTemplateEngine()

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
            self._outbox.append(command)

    def drain(self) -> list[dict[str, t.Any]]:
        queued, self._outbox = self._outbox, []
        return queued

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
        """Update a live template binding from Python."""
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
                self._outbox.append(dict(result))
            elif isinstance(result, (list, tuple)):
                for item in result:
                    if isinstance(item, dict) and "op" in item:
                        self._outbox.append(dict(item))

    async def dispatch(self, payload: dict[str, t.Any]) -> list[dict[str, t.Any]]:
        payload = dict(_plain(payload) or {})
        event = str(payload.get("type", ""))
        selector = payload.get("selector")
        handlers = list(self._handlers.get((event, selector), ()))
        if selector is not None:
            handlers.extend(self._handlers.get((event, None), ()))
        await self._run_handlers(handlers, payload)
        return self.drain()

    async def dispatch_ws(self, payload: dict[str, t.Any]) -> list[dict[str, t.Any]]:
        payload = dict(_plain(payload) or {})
        event = str(payload.get("type", ""))
        await self._run_handlers(list(self._ws_handlers.get(event, ())), payload)
        return self.drain()

    async def dispatch_json(self, payload: str) -> str:
        commands = await self.dispatch(json.loads(str(payload)))
        return json.dumps(commands, separators=(",", ":"), default=str)

    async def dispatch_ws_json(self, payload: str) -> str:
        commands = await self.dispatch_ws(json.loads(str(payload)))
        return json.dumps(commands, separators=(",", ":"), default=str)


midnight = Midnight()

__all__ = ["Midnight", "MidnightTemplateEngine", "midnight"]
