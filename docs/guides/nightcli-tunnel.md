# NightCLI direct tunnel

The `nightcli-tunnel` MVP forwards a local TCP service directly to another device without a relay or rendezvous server.

On the machine running the Night app:

~~~bash
nightcli-tunnel create \\
  --target-host 127.0.0.1 \\
  --target-port 8000 \\
  --advertise-host 192.168.1.10
~~~

On the other machine:

~~~bash
nightcli-tunnel join '<invite-code>' --local-port 3000
~~~

The remote Night app is then available at `127.0.0.1:3000`.

Use a reachable LAN address, IPv6 address, or a manually forwarded IPv4 address for `--advertise-host`. Automatic address detection is only a fallback; VPNs, containers, and multiple interfaces can make the chosen address unsuitable.

This transport is currently plaintext TCP. It is for LAN, IPv6, or controlled development environments until TLS/Noise encryption is added. The invite code acts as a bearer credential and should be treated like a password.

The original chat MVP remains available as:

~~~bash
nightcli room create
nightcli room join '<invite-code>'
~~~
