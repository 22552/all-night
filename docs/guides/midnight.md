# Midnight

Midnight is Night's Python/browser UI runtime, distributed separately as `all-night-midnight`.

Install the Night core by itself:

```bash
python -m pip install -U all-night
```

For a CPython server with Night's recommended server/runtime dependencies:

```bash
python -m pip install -U "all-night[standard]"
```

`all-night[standard]` does **not** install Midnight. The `standard` extra contains server/runtime dependencies such as `uvicorn[standard]`, `orjson`, and the Workers runtime SDK.

Install Midnight separately:

```bash
python -m pip install -U all-night-midnight
```

`all-night-midnight` depends on the matching `all-night` release and owns `night_midnight.py`, `night_midnight_scope.py`, the additional Midnight helper modules, and `midnight.js`. The core `all-night` wheel does not ship those files, avoiding two distributions owning the same module path.

## UI Midnight

Normal Midnight commands target the current UI context. Existing code does not need a delivery scope:

```python
from night_midnight import CompiledMidnight

midnight = CompiledMidnight()

@midnight.on("click", "#save")
def save(event):
    midnight.text("#status", "Saved")
    midnight.value("#count", 1)
```

The ordinary UI API remains current-context oriented:

```python
midnight.text("#status", "Ready")
midnight.html("#panel", "<strong>Done</strong>")
midnight.value("#name", "Ada")
midnight.attr("#name", "aria-label", "Name")
midnight.add_class("#panel", "ready")
midnight.remove_class("#panel", "hidden")
midnight.focus("#name")
midnight.emit("updated", {"count": 3})
```

For hybrid DOM work:

```python
from night_midnight import CompiledMidnight, js

midnight = CompiledMidnight()
field = midnight.get("#count")
field.value = js.Number(field.value) + 1
```

Ordinary Python expressions keep Python semantics; `js.*` explicitly marks browser-side JavaScript expressions.

## Direct WebSocket transport

Serve the browser runtime and connect one persistent Midnight WebSocket:

```python
from night_midnight import CompiledMidnight, MidnightWebSocketAdapter, read_midnight_js

midnight = CompiledMidnight()
midnight_ws = MidnightWebSocketAdapter(midnight)

@app.get("/midnight.js")
def runtime():
    return Response(
        read_midnight_js(),
        headers={"Content-Type": "application/javascript; charset=utf-8"},
    )

@app.websocket("/__midnight/ws")
async def socket(ws):
    await midnight_ws.serve(ws)
```

Browser:

```html
<script src="/midnight.js"></script>
<script>
const scheme = location.protocol === "https:" ? "wss:" : "ws:";
midnight.connectTransport(`${scheme}//${location.host}/__midnight/ws`);
</script>
```

Normal server events use the persistent WebSocket. `@midnight.compile` can install client-safe event programs so later matching events execute in the browser without a server round trip.

## Scoped delivery

Multi-session delivery is provided by `night_midnight_scope`:

```python
from night_midnight_scope import (
    ScopedMidnight,
    ScopedMidnightWebSocketAdapter,
    F, G, S, Q,
)

midnight = ScopedMidnight()
midnight_ws = ScopedMidnightWebSocketAdapter(midnight)
```

Normal UI commands still affect only the current connection:

```python
midnight.text("#status", "saved locally")
```

Use `.to(...)` only when selecting delivery targets:

```python
await midnight.to(F.user_id == "u123").emit("notification")

await midnight.to(
    (F.org_id == "acme")
    & (F.role.in_(["admin", "owner"]))
    & (G.document_id == 42)
).text("#status", "Document updated")
```

Calling `.to()` with no filter means all currently connected Midnight clients:

```python
await midnight.to().emit("maintenance", {"seconds": 30})
```

`midnight.all` is an equivalent explicit target.

Simple keyword filters are an `F`-scope shortcut:

```python
await midnight.to(user_id="u123").emit("notification")
await midnight.to(org_id="acme", role="admin").text("#notice", "Admin update")
```

### F / G / S / Q

The filter namespaces have different lifetimes:

```text
F = logical/session metadata
G = browser-tab metadata
S = WebSocket-connection metadata
Q = application-defined metadata
```

`F` is intended for authenticated session information such as user, organization, role, or plan. Supply trusted values from the server adapter rather than accepting arbitrary client claims:

```python
@app.websocket("/__midnight/ws")
async def socket(ws):
    await midnight_ws.serve(
        ws,
        F={
            "user_id": current_user.id,
            "org_id": current_user.org_id,
            "role": current_user.role,
        },
        Q={"deployment": "production"},
    )
```

`G` is tab-scoped. `midnight.js` stores a random tab ID in `sessionStorage`; reconnecting the WebSocket from the same tab keeps the same `G`, while another tab receives another ID.

`S` is socket-scoped. A new WebSocket connection creates fresh `S` metadata and a new connection ID. Disconnecting destroys that socket scope.

`Q` is a free application namespace for values whose meaning is defined by the application.

Inside an active scoped connection the current values can be read or extended:

```python
midnight.F.org_id
midnight.G.document_id = 42
midnight.S.ready = True
midnight.Q.feature = "beta"
```

### Filter expressions

Filters are symbolic and JSON-serializable; Python lambdas are deliberately not part of the routing API. This keeps the model compatible with future Redis/NATS/broker fan-out.

```python
expr = (
    (F.org_id == "acme")
    & (G.document_id == 42)
    & (F.role.in_(["admin", "owner"]))
    & ~(Q.suspended == True)
)

payload = midnight.filter_json(expr)
```

Supported operators include `==`, `!=`, `<`, `<=`, `>`, `>=`, `in_(...)`, `contains(...)`, `exists()`, `&`, `|`, and `~`.

The first implementation scans the local connection registry. The public filter AST is intentionally independent from that implementation so frequent fields can later be indexed, or the same query can be forwarded to other processes, without changing application code.

## Session and connection model

The concepts are intentionally separate:

```text
normal Midnight UI command
    -> current WebSocket/UI context

F logical session
    -> may cover multiple tabs/connections

G tab
    -> survives WebSocket reconnect in that tab

S socket
    -> reset on every WebSocket connection

Q application metadata
    -> application-defined meaning
```

This makes patterns such as "all tabs of this user", "everyone in this organization who currently has document 42 open", or "everyone except a particular socket state" possible without creating explicit rooms.

## Templates and live bindings

`MidnightTemplateEngine` extends Night's normal `TemplateEngine` with live bindings:

```python
from night_midnight import midnight

@app.get("/")
def home():
    return midnight.render_template_string("""
      <h1>${{ title }}</h1>
      <p>${{ count }}</p>
    """, title="Night", count=0)
```

Then update the current UI binding with:

```python
midnight.set("count", 1)
```

## Trust boundary

Never derive trusted `F` metadata from arbitrary browser payloads. Authentication and authorization remain the application's responsibility. Midnight's delivery filter only selects registered connections; it is not an authentication system.

For the lower-level unscoped runtime, `trusted_session_id()` and `dispatch_trusted()` remain available for adapters that already possess an authenticated server-side identifier.

## Browser tab identity and reconnect

The direct browser runtime automatically includes its stable tab ID with each `midnight-event`. Unexpected WebSocket closes reconnect with capped exponential backoff. Reconnection changes socket scope `S` but preserves tab scope `G` for that page.

The browser API exposes the current ID as:

```js
midnight.tabId
midnight.stats().tabId
```

## Architecture

```text
Browser tab
  midnight.js
     |  stable tab ID (G)
     |  persistent/reconnecting WebSocket
     v
ScopedMidnightWebSocketAdapter
     |-- F: trusted logical-session metadata
     |-- G: tab metadata
     |-- S: current socket metadata
     `-- Q: application metadata
              |
              v
       serializable filter AST
              |
      current process scan today
      broker/index fan-out later
```

Midnight keeps current-context UI operations simple while making multi-session delivery explicit through `.to(...)`.
