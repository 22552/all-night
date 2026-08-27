"""Midnight public runtime with execution-mode extensions.

The original runtime stays in ``_night_midnight_core``. This module keeps its
public API and adds four explicit execution modes:

- ``server``: always execute the handler in Python on the server/runtime.
- ``compile``: existing first-event trace to Midnight's compact client IR.
- ``static``: trace that IR at registration time and install it before events.
- ``full_compile``: route the handler to the page's local Pyodide runtime when
  Browser Night is available, with ordinary server execution as the fallback.
"""

from __future__ import annotations

import functools
import inspect
import secrets
import sys
import types
import typing as t

try:
    import _night_midnight_core as _core
except ModuleNotFoundError:
    # Browser Night source mode historically writes only night_midnight.py into
    # /night. Installed wheels already contain the core module, so this path is
    # only used by Pyodide's source loader.
    try:
        from pyodide.http import open_url  # type: ignore
    except ImportError:
        raise
    source = open_url(
        "https://raw.githubusercontent.com/22552/all-night/main/_night_midnight_core.py"
    ).read()
    module = types.ModuleType("_night_midnight_core")
    module.__file__ = "/night/_night_midnight_core.py"
    sys.modules["_night_midnight_core"] = module
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    _core = module

from _night_midnight_core import *


class CompiledMidnight(_core.CompiledMidnight):
    """Midnight with explicit Server/Compile/Static/FullCompile modes."""

    def __init__(self, *args: t.Any, **kwargs: t.Any) -> None:
        super().__init__(*args, **kwargs)
        self._initial_client_programs: dict[str, dict[str, t.Any]] = {}
        self._full_compile_handlers: dict[str, t.Callable[..., t.Any]] = {}
        self._handlers.setdefault(("custom:__full_compile", None), []).append(
            self._run_full_compile_event
        )

    def on(
        self,
        event: str,
        selector: str | None = None,
        *,
        prevent_default: bool = False,
    ):
        register = super().on(event, selector, prevent_default=prevent_default)

        def decorator(fn: t.Callable[..., t.Any]):
            registered = register(fn)
            spec = getattr(registered, "__midnight_compile_spec__", None)
            if not isinstance(spec, dict):
                return registered
            mode = spec.get("mode")
            if mode == "Static" and not spec.get("prepared"):
                self._prepare_static(registered, spec)
            elif mode == "FullCompile" and not spec.get("prepared"):
                self._prepare_full_compile(registered, spec)
            return registered

        return decorator

    def server(self, fn: t.Callable[..., t.Any] | None = None):
        """Mark a handler as explicit server execution."""

        def decorate(func: t.Callable[..., t.Any]):
            setattr(func, "__midnight_execution_mode__", "Server")
            return func

        return decorate if fn is None else decorate(fn)

    def static(self, fn: t.Callable[..., t.Any] | None = None):
        """Compile a handler to client IR at registration time."""

        def decorate(func: t.Callable[..., t.Any]):
            spec: dict[str, t.Any] = {
                "id": self._handler_id(func),
                "mode": "Static",
                "event": None,
                "selector": None,
                "prevent_default": False,
                "prepared": False,
            }

            @functools.wraps(func)
            def wrapper(event: t.Any = None, *args: t.Any, **kwargs: t.Any):
                return None

            wrapper.__midnight_compile_spec__ = spec
            wrapper.__midnight_original__ = func
            return wrapper

        return decorate if fn is None else decorate(fn)

    def full_compile(self, fn: t.Callable[..., t.Any] | None = None):
        """Run a handler in local Pyodide when available.

        Browser Night already owns the application's Python runtime in the
        parent page, so FullCompile installs only a compact handler manifest in
        the DOM runtime. Matching events are routed back to that local Pyodide
        instance without a server/network round trip. Clients that do not
        understand the manifest keep sending ordinary events, which execute
        the original Python handler as a fallback.
        """

        def decorate(func: t.Callable[..., t.Any]):
            spec: dict[str, t.Any] = {
                "id": self._handler_id(func),
                "mode": "FullCompile",
                "event": None,
                "selector": None,
                "prevent_default": False,
                "prepared": False,
            }

            @functools.wraps(func)
            def wrapper(event: t.Any = None, *args: t.Any, **kwargs: t.Any):
                local = event.get("__midnight_local_handlers", ()) if isinstance(event, dict) else ()
                if spec["id"] in local:
                    return None
                return func(event, *args, **kwargs)

            wrapper.__midnight_compile_spec__ = spec
            wrapper.__midnight_original__ = func
            return wrapper

        return decorate if fn is None else decorate(fn)

    def _prepare_static(
        self,
        wrapper: t.Callable[..., t.Any],
        spec: dict[str, t.Any],
    ) -> None:
        if spec.get("event") is None:
            raise _core.MidnightCompileError("@midnight.static must be registered with @midnight.on")
        if self._compile_program is not None:
            raise _core.MidnightCompileError("nested Midnight tracing is not supported")

        original = getattr(wrapper, "__midnight_original__", wrapper)
        program: list[dict[str, t.Any]] = []
        self._compile_program = program
        try:
            result = original(_core.EventExpr())
            if inspect.isawaitable(result):
                raise _core.MidnightCompileError("async static handlers are not supported yet")
        finally:
            self._compile_program = None

        if not program:
            raise _core.MidnightCompileError("static handler produced no client-side commands")

        spec["prepared"] = True
        self._initial_client_programs[spec["id"]] = {
            "op": "compiled_install",
            "mode": "Static",
            "handler_id": spec["id"],
            "event": spec["event"],
            "selector": spec["selector"],
            "prevent_default": spec["prevent_default"],
            "program": program,
            "execute_now": False,
        }

    def _prepare_full_compile(
        self,
        wrapper: t.Callable[..., t.Any],
        spec: dict[str, t.Any],
    ) -> None:
        if spec.get("event") is None:
            raise _core.MidnightCompileError(
                "@midnight.full_compile must be registered with @midnight.on"
            )
        original = getattr(wrapper, "__midnight_original__", wrapper)
        self._full_compile_handlers[spec["id"]] = original
        spec["prepared"] = True
        self._initial_client_programs[spec["id"]] = {
            "op": "full_compiled_install",
            "mode": "FullCompile",
            "handler_id": spec["id"],
            "event": spec["event"],
            "selector": spec["selector"],
            "prevent_default": spec["prevent_default"],
        }

    async def _run_full_compile_event(self, payload: dict[str, t.Any]) -> None:
        detail = payload.get("detail") if isinstance(payload, dict) else None
        if not isinstance(detail, dict):
            return
        handler_id = str(detail.get("handler_id", ""))
        handler = self._full_compile_handlers.get(handler_id)
        if handler is None:
            self.emit(
                "error",
                {
                    "mode": "FullCompile",
                    "error": "unknown FullCompile handler",
                    "handler_id": handler_id,
                },
            )
            return

        event = detail.get("event")
        if not isinstance(event, dict):
            event = {}
        result = handler(event)
        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, dict) and "op" in result:
            self.current_session.push(dict(result))
        elif isinstance(result, (list, tuple)):
            for item in result:
                if isinstance(item, dict) and "op" in item:
                    self.current_session.push(dict(item))

    def client_programs(self) -> list[dict[str, t.Any]]:
        programs: list[dict[str, t.Any]] = []
        for stored in self._initial_client_programs.values():
            command = dict(stored)
            command["exclusive"] = self._compiled_pair_is_exclusive(
                str(command["event"]), command.get("selector")
            )
            programs.append(command)
        return programs

    def client_programs_json(self) -> str:
        return _core.json.dumps(self.client_programs(), separators=(",", ":"), default=str)

    def _queue_initial_programs(self) -> None:
        session = self.current_session
        queued = getattr(session, "_midnight_initial_programs", None)
        if queued is None:
            queued = set()
            setattr(session, "_midnight_initial_programs", queued)
        for command in self.client_programs():
            handler_id = str(command["handler_id"])
            if handler_id in queued:
                continue
            queued.add(handler_id)
            payload = dict(command)
            op = str(payload.pop("op"))
            _core.Midnight._push(self, op, **payload)

    def subscriptions_json(self) -> str:
        self._queue_initial_programs()
        return super().subscriptions_json()


class MidnightWebSocketAdapter(_core.MidnightWebSocketAdapter):
    """WebSocket adapter that pre-installs Static client programs."""

    async def serve(self, ws: t.Any) -> None:
        session_id = _core.trusted_session_id(secrets.token_urlsafe(24))
        await ws.accept()
        await ws.send_json(
            {
                "type": "midnight-config",
                "subscriptions": self.midnight.subscriptions(),
            }
        )
        if isinstance(self.midnight, CompiledMidnight):
            programs = self.midnight.client_programs()
            if programs:
                await ws.send_json(
                    {
                        "type": "midnight-commands",
                        "event_id": 0,
                        "commands": programs,
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


async def serve_midnight_ws(midnight: _core.Midnight, ws: t.Any) -> None:
    await MidnightWebSocketAdapter(midnight).serve(ws)


_default_midnight: CompiledMidnight | None = None


def get_default_midnight() -> CompiledMidnight:
    global _default_midnight
    if _default_midnight is None:
        _default_midnight = CompiledMidnight()
    return _default_midnight


def reset_default_midnight() -> CompiledMidnight:
    global _default_midnight
    _default_midnight = CompiledMidnight()
    return _default_midnight


class _DefaultMidnightProxy:
    __slots__ = ()

    def __getattr__(self, name: str) -> t.Any:
        return getattr(get_default_midnight(), name)

    def __repr__(self) -> str:
        if _default_midnight is None:
            return "<midnight lazy>"
        return repr(_default_midnight)


midnight: CompiledMidnight = t.cast(CompiledMidnight, _DefaultMidnightProxy())

__all__ = list(_core.__all__)
