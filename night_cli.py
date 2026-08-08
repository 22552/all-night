#!/usr/bin/env python3
"""NightCLI: direct, relay-free rooms for Night development.

This MVP deliberately has no rendezvous or relay service. The room creator
listens on a local TCP socket and shares a self-contained invite code.
It is intended for LAN, IPv6, or a manually forwarded port.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import secrets
import socket
import sys
import uuid
from dataclasses import asdict, dataclass
from typing import Any


_PROTOCOL = "nightcli/0.1"
_MAX_LINE = 64 * 1024


@dataclass(frozen=True)
class Invite:
    room: str
    host: str
    port: int
    token: str
    protocol: str = _PROTOCOL

    def encode(self) -> str:
        raw = json.dumps(asdict(self), separators=(",", ":"), sort_keys=True).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    @classmethod
    def decode(cls, value: str) -> "Invite":
        padded = value + "=" * (-len(value) % 4)
        try:
            data = json.loads(base64.urlsafe_b64decode(padded).decode())
            invite = cls(
                room=str(data["room"]),
                host=str(data["host"]),
                port=int(data["port"]),
                token=str(data["token"]),
                protocol=str(data.get("protocol", "")),
            )
        except (ValueError, KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid NightCLI invite code") from exc
        if invite.protocol != _PROTOCOL:
            raise ValueError(f"unsupported invite protocol: {invite.protocol!r}")
        if not invite.room or not invite.token or not (1 <= invite.port <= 65535):
            raise ValueError("invalid invite fields")
        return invite


def _line(data: dict[str, Any]) -> bytes:
    return (json.dumps(data, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


async def _read_message(reader: asyncio.StreamReader) -> dict[str, Any]:
    raw = await reader.readline()
    if not raw:
        raise EOFError
    if len(raw) > _MAX_LINE:
        raise ValueError("message is too large")
    value = json.loads(raw.decode())
    if not isinstance(value, dict):
        raise ValueError("message must be an object")
    return value


class RoomServer:
    def __init__(self, invite: Invite) -> None:
        self.invite = invite
        self.clients: set[asyncio.StreamWriter] = set()
        self.names: dict[asyncio.StreamWriter, str] = {}

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            hello = await asyncio.wait_for(_read_message(reader), timeout=10)
            if (
                hello.get("type") != "hello"
                or hello.get("room") != self.invite.room
                or not secrets.compare_digest(str(hello.get("token", "")), self.invite.token)
            ):
                writer.write(_line({"type": "error", "error": "room authentication failed"}))
                await writer.drain()
                return

            name = str(hello.get("name") or "anonymous")[:64]
            self.clients.add(writer)
            self.names[writer] = name
            writer.write(_line({"type": "welcome", "room": self.invite.room, "protocol": _PROTOCOL}))
            await writer.drain()
            await self.broadcast({"type": "system", "text": f"{name} joined the room"}, exclude=writer)

            while True:
                message = await _read_message(reader)
                if message.get("type") != "message":
                    continue
                text = str(message.get("text", ""))
                if not text:
                    continue
                await self.broadcast({"type": "message", "name": name, "text": text[:16_384]})
        except (EOFError, asyncio.IncompleteReadError, ConnectionError, ValueError, asyncio.TimeoutError):
            pass
        finally:
            was_present = writer in self.clients
            name = self.names.pop(writer, "anonymous")
            self.clients.discard(writer)
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass
            if was_present:
                await self.broadcast({"type": "system", "text": f"{name} left the room"})

    async def broadcast(self, message: dict[str, Any], *, exclude: asyncio.StreamWriter | None = None) -> None:
        dead: list[asyncio.StreamWriter] = []
        for writer in tuple(self.clients):
            if writer is exclude:
                continue
            try:
                writer.write(_line(message))
                await writer.drain()
            except (ConnectionError, BrokenPipeError):
                dead.append(writer)
        for writer in dead:
            self.clients.discard(writer)


def _default_advertise_host() -> str:
    try:
        return socket.gethostbyname(socket.gethostname())
    except socket.gaierror:
        return "127.0.0.1"


async def create_room(args: argparse.Namespace) -> int:
    host = args.bind_host
    advertised = args.advertise_host or _default_advertise_host()
    token = secrets.token_urlsafe(24)
    room = str(uuid.uuid4())
    server = RoomServer(Invite(room, advertised, args.port, token))
    listener = await asyncio.start_server(server.handle, host, args.port)
    actual_port = listener.sockets[0].getsockname()[1] if listener.sockets else args.port
    server.invite = Invite(room, advertised, actual_port, token)

    print("NightCLI direct room", flush=True)
    print(f"room:   {room}", flush=True)
    print(f"listen: {host}:{actual_port}", flush=True)
    print("invite:", flush=True)
    print(server.invite.encode(), flush=True)
    print("No relay server is used. Share the invite only with the intended peer.", flush=True)
    print("Type a message, or press Ctrl-C to stop.", flush=True)

    async with listener:
        await asyncio.gather(listener.serve_forever(), _stdin_sender(server))

    return 0


async def _stdin_sender(server: RoomServer) -> None:
    loop = asyncio.get_running_loop()
    while True:
        text = await loop.run_in_executor(None, sys.stdin.readline)
        if not text:
            return
        text = text.rstrip("\n")
        if text:
            await server.broadcast({"type": "message", "name": "you", "text": text[:16_384]})


async def join_room(args: argparse.Namespace) -> int:
    invite = Invite.decode(args.invite)
    reader, writer = await asyncio.open_connection(invite.host, invite.port)
    writer.write(_line({"type": "hello", "room": invite.room, "token": invite.token, "name": args.name}))
    await writer.drain()

    welcome = await _read_message(reader)
    if welcome.get("type") != "welcome":
        raise RuntimeError(welcome.get("error", "room rejected the connection"))
    print(f"connected to room {invite.room}", flush=True)

    async def receive() -> None:
        try:
            while True:
                message = await _read_message(reader)
                kind = message.get("type")
                if kind == "message":
                    print(f"{message.get('name', 'peer')}: {message.get('text', '')}", flush=True)
                elif kind == "system":
                    print(f"* {message.get('text', '')}", flush=True)
        except (EOFError, asyncio.IncompleteReadError, ConnectionError, ValueError):
            print("* connection closed", flush=True)

    receiver = asyncio.create_task(receive())
    loop = asyncio.get_running_loop()
    try:
        while not receiver.done():
            text = await loop.run_in_executor(None, sys.stdin.readline)
            if not text:
                break
            text = text.rstrip("\n")
            if text:
                writer.write(_line({"type": "message", "text": text[:16_384]}))
                await writer.drain()
    finally:
        receiver.cancel()
        writer.close()
        await writer.wait_closed()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nightcli", description="Direct, relay-free Night rooms")
    sub = parser.add_subparsers(dest="command", required=True)
    room = sub.add_parser("room", help="create or join a direct room")
    room_sub = room.add_subparsers(dest="room_command", required=True)

    create = room_sub.add_parser("create", help="listen for direct TCP connections")
    create.add_argument("--bind-host", default="0.0.0.0")
    create.add_argument("--advertise-host", help="address the peer can reach")
    create.add_argument("--port", type=int, default=0, help="TCP port; 0 chooses a free port")
    create.set_defaults(handler=create_room)

    join = room_sub.add_parser("join", help="connect using an invite code")
    join.add_argument("invite")
    join.add_argument("--name", default="anonymous")
    join.set_defaults(handler=join_room)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(args.handler(args))
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"nightcli: error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
