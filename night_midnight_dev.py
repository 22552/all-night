"""Dependency-free development helpers for Midnight.

``HotReload`` uses Night's existing WebSocket support and polls files with the
standard library only. It is intentionally kept outside ``night.py`` and the
normal Midnight runtime so production imports do not start watcher machinery.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import pathlib
import typing as t


Render = t.Callable[[], str | t.Awaitable[str]]


class HotReload:
    """Watch files and notify connected browsers through a Night WebSocket.

    ``mode='reload'`` performs a full browser reload. ``mode='component'`` sends
    freshly rendered HTML for ``selector`` instead. The latter requires a
    ``render`` callback and is useful with :class:`night_midnight_component.Component`.
    """

    def __init__(
        self,
        app,
        paths: t.Iterable[str | os.PathLike[str]] | None = None,
        *,
        websocket_path: str = "/__midnight_reload",
        interval: float = 0.35,
        mode: str = "reload",
        selector: str | None = None,
        render: Render | None = None,
    ) -> None:
        mode = str(mode).lower()
        if mode not in {"reload", "component"}:
            raise ValueError("mode must be 'reload' or 'component'")
        if mode == "component" and (not selector or render is None):
            raise ValueError("component mode requires selector and render")
        if interval <= 0:
            raise ValueError("interval must be positive")

        self.app = app
        self.paths = tuple(pathlib.Path(p) for p in (paths or (".",)))
        self.websocket_path = str(websocket_path)
        self.interval = float(interval)
        self.mode = mode
        self.selector = str(selector) if selector is not None else None
        self.render = render
        self._clients: set[t.Any] = set()
        self._task: asyncio.Task[None] | None = None
        self._snapshot = self._scan()

        app.websocket(self.websocket_path)(self._socket)

    @staticmethod
    def _ignored(path: pathlib.Path) -> bool:
        return any(part in {".git", "__pycache__", ".venv", "venv", "node_modules"} for part in path.parts)

    def _iter_files(self):
        for root in self.paths:
            if root.is_file():
                yield root
                continue
            if not root.exists():
                continue
            for current, dirs, files in os.walk(root):
                dirs[:] = [
                    name
                    for name in dirs
                    if name not in {".git", "__pycache__", ".venv", "venv", "node_modules"}
                ]
                base = pathlib.Path(current)
                for name in files:
                    path = base / name
                    if not self._ignored(path):
                        yield path

    def _scan(self) -> dict[str, tuple[int, int]]:
        snapshot: dict[str, tuple[int, int]] = {}
        for path in self._iter_files():
            try:
                stat = os.stat(path)
            except (FileNotFoundError, PermissionError, OSError):
                continue
            snapshot[str(path.resolve())] = (stat.st_mtime_ns, stat.st_size)
        return snapshot

    def changed(self) -> bool:
        """Scan once and report whether any watched file changed."""
        current = self._scan()
        changed = current != self._snapshot
        self._snapshot = current
        return changed

    async def _message(self) -> dict[str, t.Any]:
        if self.mode == "reload":
            return {"type": "reload"}
        assert self.render is not None and self.selector is not None
        html = self.render()
        if inspect.isawaitable(html):
            html = await html
        return {"type": "component", "selector": self.selector, "html": str(html)}

    async def _broadcast(self, message: dict[str, t.Any]) -> None:
        stale = []
        for ws in tuple(self._clients):
            try:
                await ws.send_json(message)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self._clients.discard(ws)

    async def _watch(self) -> None:
        try:
            while self._clients:
                await asyncio.sleep(self.interval)
                if self.changed():
                    await self._broadcast(await self._message())
        finally:
            self._task = None

    async def _socket(self, ws) -> None:
        await ws.accept()
        self._clients.add(ws)
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._watch())
        try:
            while True:
                await ws.receive_text()
        except Exception:
            pass
        finally:
            self._clients.discard(ws)

    def client_script(self) -> str:
        """Return the tiny browser client used during development."""
        path = json.dumps(self.websocket_path)
        return f"""<script>(()=>{{
const p={path};
const proto=location.protocol==='https:'?'wss:':'ws:';
const ws=new WebSocket(proto+'//'+location.host+p);
ws.onmessage=(event)=>{{
  let message; try {{ message=JSON.parse(event.data); }} catch {{ return; }}
  if(message.type==='reload') location.reload();
  else if(message.type==='component' && message.selector) {{
    document.querySelectorAll(message.selector).forEach(el=>{{el.innerHTML=message.html??'';}});
  }}
}};
}})();</script>"""


__all__ = ["HotReload"]
