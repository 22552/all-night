# NightCLI

NightCLI is a small direct-connection CLI for Night experiments. The MVP does
not use a rendezvous, relay, or central server: the room creator listens on a
TCP port and shares a self-contained invite code.

## Install

From a checkout:

```bash
pip install -e .
```

This exposes the `nightcli` command.

## Same-machine test

Terminal 1:

```bash
nightcli room create --advertise-host 127.0.0.1 --port 8765
```

Terminal 2:

```bash
nightcli room join '<invite-code>' --name alice
```

Copy the complete invite code printed by the first terminal.

## Connecting two devices

Use an address reachable by the peer:

- an address on the same LAN;
- a reachable IPv6 address; or
- an IPv4 address with a manually forwarded TCP port.

The invite code contains the address and port, room UUID, and a random
authentication token. It is not a public URL and should only be shared with
the intended peer.

This initial protocol is plaintext TCP and is for development/LAN use. It does
not yet provide end-to-end encryption, NAT traversal, automatic discovery, or
a relay fallback. Those are deliberately separate next steps.

## Commands

```text
nightcli room create [--bind-host HOST] [--advertise-host HOST] [--port PORT]
nightcli room join INVITE [--name NAME]
```
