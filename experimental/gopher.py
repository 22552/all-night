"""Experimental zero-dependency Gopher adapter for Night.

This intentionally lives outside ``night.py`` for now.  It lets a Night app
also expose a tiny RFC 1436-style Gopher service without changing the ASGI
core.

Example::

    import asyncio
    from night import Night
    from experimental.gopher import Gopher, menu

    app = Night()
    gopher = Gopher(app)

    @gopher.get("/")
    def index():
        return menu(
            ("i", "Night on Gopher!", "", ""),
            ("1", "About", "/about"),
            ("0", "Plain text", "/hello.txt"),
        )

    @gopher.get("/about")
    def about():
        return menu(("i", "A tiny Gopher service powered by Night.", "", ""))

    @gopher.get("/hello.txt")
    def hello():
        return "hello from Night\n"

    asyncio.run(gopher.serve(host="::", port=7070))
"""

from __future__ import annotations

import asyncio
import dataclasses
import inspect
import typing as t

try:
    from night import Night
except ImportError:  # pragma: no cover - useful when copied next to night.py
    Night = t.Any  # type: ignore[misc,assignment]


@dataclasses.dataclass(slots=True)
class GopherRequest:
    """A single Gopher selector request."""

    selector: str
    peer: t.Any = None

    @property
    def query(self) -> str | None:
        """Return the Gopher search query, if the selector contains a tab."""
        if "\t" not in self.selector:
            return None
        return self.selector.split("\t", 1)[1]

    @property
    def path(self) -> str:
        path = self.selector.split("\t", 1)[0]
        return path or "/"


@dataclasses.dataclass(slots=True)
class GopherItem:
    """One line in a Gopher menu."""

    item_type: str
    display: str
    selector: str = ""
    host: str | None = None
    port: int | None = None

    def render(self, default_host: str, default_port: int) -> str:
        item_type = (self.item_type or "i")[0]
        display = _clean_field(self.display)
        selector = _clean_field(self.selector)
        host = _clean_field(self.host if self.host is not None else default_host)
        port = self.port if self.port is not None else default_port
        return f"{item_type}{display}\t{selector}\t{host}\t{int(port)}"


@dataclasses.dataclass(slots=True)
class GopherMenu:
    items: list[GopherItem]


@dataclasses.dataclass(slots=True)
class GopherResponse:
    body: bytes
    menu: bool = False


def item(
    item_type: str,
    display: str,
    selector: str = "",
    host: str | None = None,
    port: int | None = None,
) -> GopherItem:
    return GopherItem(item_type, display, selector, host, port)


def menu(*items: GopherItem | tuple[t.Any, ...]) -> GopherMenu:
    out: list[GopherItem] = []
    for value in items:
        if isinstance(value, GopherItem):
            out.append(value)
        else:
            out.append(GopherItem(*value))
    return GopherMenu(out)


def _clean_field(value: t.Any) -> str:
    return str(value).replace("\r", " ").replace("\n", " ").replace("\t", " ")


def _dot_stuff(lines: t.Iterable[str]) -> str:
    out = []
    for line in lines:
        line = line.rstrip("\r\n")
        if line.startswith("."):
            line = "." + line
        out.append(line)
    return "\r\n".join(out) + "\r\n.\r\n"


Handler = t.Callable[..., t.Any]


class Gopher:
    """Tiny Gopher router/server designed to sit beside a Night app.

    Gopher is not ASGI, so it cannot be served by Uvicorn.  This adapter owns a
    small ``asyncio.start_server`` listener while the ordinary Night app keeps
    using its normal ASGI server.
    """

    def __init__(self, app: Night | None = None, *, hostname: str = "localhost"):
        self.app = app
        self.hostname = hostname
        self.routes: dict[str, Handler] = {}
        if app is not None and hasattr(app, "extensions"):
            app.extensions["gopher"] = self

    def get(self, selector: str):
        selector = selector or "/"

        def decorator(fn: Handler) -> Handler:
            self.routes[selector] = fn
            return fn

        return decorator

    route = get

    async def dispatch(self, req: GopherRequest, *, host: str, port: int) -> bytes:
        fn = self.routes.get(req.path)
        if fn is None:
            return self._encode_menu(
                GopherMenu([GopherItem("3", "Not found", "", host, port)]),
                host,
                port,
            )

        try:
            result = self._invoke(fn, req)
            if inspect.isawaitable(result):
                result = await result
            return self._encode(result, host, port)
        except Exception as exc:
            # Gopher item type 3 is the conventional error item.
            return self._encode_menu(
                GopherMenu([GopherItem("3", f"Internal error: {type(exc).__name__}", "", host, port)]),
                host,
                port,
            )

    @staticmethod
    def _invoke(fn: Handler, req: GopherRequest):
        try:
            sig = inspect.signature(fn)
        except (TypeError, ValueError):
            return fn(req)
        if not sig.parameters:
            return fn()
        return fn(req)

    def _encode(self, value: t.Any, host: str, port: int) -> bytes:
        if isinstance(value, GopherResponse):
            return value.body
        if isinstance(value, GopherMenu):
            return self._encode_menu(value, host, port)
        if isinstance(value, GopherItem):
            return self._encode_menu(GopherMenu([value]), host, port)
        if isinstance(value, bytes):
            return value
        if value is None:
            value = ""
        # RFC 1436 text responses use CRLF and a single-dot terminator.
        return _dot_stuff(str(value).splitlines()).encode("utf-8")

    @staticmethod
    def _encode_menu(value: GopherMenu, host: str, port: int) -> bytes:
        lines = [entry.render(host, port) for entry in value.items]
        return ("\r\n".join(lines) + "\r\n.\r\n").encode("utf-8")

    async def _handle(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        *,
        public_host: str,
        public_port: int,
        max_selector: int,
    ) -> None:
        try:
            raw = await reader.readline()
            if len(raw) > max_selector:
                writer.write(
                    self._encode_menu(
                        GopherMenu([GopherItem("3", "Selector too long", "", public_host, public_port)]),
                        public_host,
                        public_port,
                    )
                )
                await writer.drain()
                return

            selector = raw.rstrip(b"\r\n").decode("utf-8", errors="replace")
            req = GopherRequest(selector=selector, peer=writer.get_extra_info("peername"))
            writer.write(await self.dispatch(req, host=public_host, port=public_port))
            await writer.drain()
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    async def serve(
        self,
        host: str = "127.0.0.1",
        port: int = 7070,
        *,
        public_host: str | None = None,
        public_port: int | None = None,
        max_selector: int = 4096,
    ) -> None:
        """Run the Gopher listener until cancelled."""

        advertised_host = public_host or self.hostname or host
        advertised_port = int(public_port if public_port is not None else port)

        async def connected(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
            await self._handle(
                reader,
                writer,
                public_host=advertised_host,
                public_port=advertised_port,
                max_selector=max_selector,
            )

        server = await asyncio.start_server(connected, host, port)
        sockets = ", ".join(str(sock.getsockname()) for sock in server.sockets or ())
        print(f"Night Gopher listening on {sockets}")
        async with server:
            await server.serve_forever()


__all__ = [
    "Gopher",
    "GopherItem",
    "GopherMenu",
    "GopherRequest",
    "GopherResponse",
    "item",
    "menu",
]
