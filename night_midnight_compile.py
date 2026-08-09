"""Client-side compiled event handlers for Midnight.

``@midnight.compile`` traces a client-safe handler on its first invocation,
installs the resulting command program in the browser, and lets later matching
events execute without a server round-trip.
"""

from __future__ import annotations

import functools
import hashlib
import inspect
import typing as t

from night_midnight_hybrid import ClientExpr, HybridExpressionError, HybridMidnight


class MidnightCompileError(HybridExpressionError):
    """Raised when a handler cannot be safely compiled for browser execution."""


class EventExpr(ClientExpr):
    """Symbolic reference to a property of the browser event."""

    __slots__ = ("path",)

    def __init__(self, path: tuple[str, ...] = ()) -> None:
        self.path = path
        super().__init__({"kind": "event", "path": list(path)})

    def __getitem__(self, key: str) -> "EventExpr":
        return EventExpr((*self.path, str(key)))

    def get(self, key: str, default: t.Any = None) -> ClientExpr:
        return ClientExpr({
            "kind": "event_get",
            "path": [*self.path, str(key)],
            "default": default,
        })

    def __getattr__(self, name: str) -> "EventExpr":
        if name.startswith("_"):
            raise AttributeError(name)
        return EventExpr((*self.path, name))


class CompiledMidnight(HybridMidnight):
    """HybridMidnight with lazy client-side event-program compilation."""

    def __init__(self, *args: t.Any, **kwargs: t.Any) -> None:
        super().__init__(*args, **kwargs)
        self._compile_program: list[dict[str, t.Any]] | None = None

    def on(
        self,
        event: str,
        selector: str | None = None,
        *,
        prevent_default: bool = False,
    ):
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

        raise MidnightCompileError(
            f"{op!r} requires server execution and cannot be used inside @midnight.compile"
        )

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
        """Compile a client-safe event handler after its first server invocation.

        Supported operations in the MVP are client expressions (``js.*``), DOM
        reads embedded in those expressions, event references, and literal DOM
        assignments. A server-only Midnight command raises ``MidnightCompileError``.

        Installation is tracked per Midnight session. This is important for a
        real WebSocket deployment: one browser compiling a handler must not stop
        another browser from receiving its own ``compiled_install`` command.
        """

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


__all__ = [
    "CompiledMidnight",
    "EventExpr",
    "MidnightCompileError",
]
