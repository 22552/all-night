#!/usr/bin/env python3
"""Direct TCP tunnelling for NightCLI.

No relay or rendezvous service is involved. The creator's process accepts a
NightCLI handshake and pipes the connection to a local TCP service.
"""

from __future__ import annotations

import argparse
import asyncio
import socket
import sys

from night_cli import Invite, _line, _read_message


def detect_address(family: int) -> str:
    candidates = (
        ("2001:4860:4860::8888", 53) if family == socket.AF_INET6
        else ("8.8.8.8", 53)
    )
    sock = socket.socket(family, socket.SOCK_DGRAM)
    try:
        sock.settimeout(0.5)
        sock.connect(candidates)
        return sock.getsockname()[0]
    except OSError:
        return "::1" if family == socket.AF_INET6 else "127.0.0.1"
    finally:
        sock.close()


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await reader.read(64 * 1024)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (ConnectionError, asyncio.IncompleteReadError):
        pass
    finally:
        writer.close()


class TunnelServer:
    def __init__(self, target_host: str, target_port: int, invite: Invite) -> None:
        self.target_host = target_host
        self.target_port = target_port
        self.invite = invite

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        target_writer: asyncio.StreamWriter | None = None
        try:
            hello = await asyncio.wait_for(_read_message(reader), timeout=10)
            if (
                hello.get("type") != "hello"
                or hello.get("room") != self.invite.room
                or hello.get("token") != self.invite.token
                or hello.get("mode") != "tunnel"
            ):
                writer.write(_line({"type": "error", "error": "tunnel authentication failed"}))
                await writer.drain()
                return

            target_reader, target_writer = await asyncio.open_connection(
                self.target_host, self.target_port
            )
            writer.write(_line({
                "type": "welcome",
                "room": self.invite.room,
                "mode": "tunnel",
                "protocol": "nightcli/0.1",
            }))
            await writer.drain()
            await asyncio.gather(
                pipe(reader, target_writer),
                pipe(target_reader, writer),
            )
        except (OSError, ValueError, asyncio.TimeoutError, ConnectionError):
            try:
                writer.write(_line({"type": "error", "error": "target connection failed"}))
                await writer.drain()
            except (ConnectionError, OSError):
                pass
        finally:
            writer.close()
            if target_writer is not None:
                target_writer.close()
            await asyncio.gather(
                writer.wait_closed(),
                target_writer.wait_closed() if target_writer is not None else asyncio.sleep(0),
                return_exceptions=True,
            )


async def create(args: argparse.Namespace) -> int:
    family = socket.AF_INET6 if ":" in args.bind_host else socket.AF_INET
    advertised = args.advertise_host or detect_address(family)
    token = __import__("secrets").token_urlsafe(24)
    import uuid
    room = str(uuid.uuid4())

    # Port 0 is useful for local testing; the actual port is placed in the invite.
    invite = Invite(room, advertised, args.port, token)
    server = TunnelServer(args.target_host, args.target_port, invite)
    listener = await asyncio.start_server(
        server.handle, args.bind_host, args.port, family=family
    )
    actual_port = listener.sockets[0].getsockname()[1]
    server.invite = Invite(room, advertised, actual_port, token)

    print(f"NightCLI tunnel listening on {args.bind_host}:{actual_port}", flush=True)
    print(f"target: {args.target_host}:{args.target_port}", flush=True)
    print("invite:", server.invite.encode(), flush=True)
    print("Direct TCP only; no relay server is used.", flush=True)
    async with listener:
        await listener.serve_forever()
    return 0


async def _proxy_local(
    invite: Invite,
    local_reader: asyncio.StreamReader,
    local_writer: asyncio.StreamWriter,
    name: str,
) -> None:
    remote_writer: asyncio.StreamWriter | None = None
    try:
        remote_reader, remote_writer = await asyncio.open_connection(invite.host, invite.port)
        remote_writer.write(_line({
            "type": "hello",
            "room": invite.room,
            "token": invite.token,
            "mode": "tunnel",
            "name": name,
        }))
        await remote_writer.drain()
        welcome = await _read_message(remote_reader)
        if welcome.get("type") != "welcome":
            raise ConnectionError(welcome.get("error", "tunnel rejected"))
        await asyncio.gather(
            pipe(local_reader, remote_writer),
            pipe(remote_reader, local_writer),
        )
    except (OSError, ValueError, ConnectionError, asyncio.IncompleteReadError):
        pass
    finally:
        local_writer.close()
        if remote_writer is not None:
            remote_writer.close()
        await asyncio.gather(
            local_writer.wait_closed(),
            remote_writer.wait_closed() if remote_writer is not None else asyncio.sleep(0),
            return_exceptions=True,
        )


async def join(args: argparse.Namespace) -> int:
    invite = Invite.decode(args.invite)
    family = socket.AF_INET6 if ":" in invite.host else socket.AF_INET
    listener = await asyncio.start_server(
        lambda r, w: _proxy_local(invite, r, w, args.name),
        args.bind_host,
        args.local_port,
        family=family,
    )
    actual_port = listener.sockets[0].getsockname()[1]
    print(f"NightCLI local tunnel: {args.bind_host}:{actual_port}", flush=True)
    print(f"remote room: {invite.room}", flush=True)
    async with listener:
        await listener.serve_forever()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nightcli-tunnel")
    sub = parser.add_subparsers(dest="command", required=True)

    create_parser = sub.add_parser("create")
    create_parser.add_argument("--target-host", default="127.0.0.1")
    create_parser.add_argument("--target-port", type=int, required=True)
    create_parser.add_argument("--bind-host", default="0.0.0.0")
    create_parser.add_argument("--advertise-host")
    create_parser.add_argument("--port", type=int, default=0)
    create_parser.set_defaults(handler=create)

    join_parser = sub.add_parser("join")
    join_parser.add_argument("invite")
    join_parser.add_argument("--bind-host", default="127.0.0.1")
    join_parser.add_argument("--local-port", type=int, default=0)
    join_parser.add_argument("--name", default="nightcli")
    join_parser.set_defaults(handler=join)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(args.handler(args))
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"nightcli-tunnel: error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
