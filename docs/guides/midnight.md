# Midnight

Midnight is Browser Night's bidirectional bridge between Python and the rendered HTML page.

It has two transports:

- **Local DOM bridge** — browser events are captured in JavaScript and dispatched directly into Python running in Pyodide. This uses `postMessage`, not a loopback WebSocket, so local UI events stay lightweight.
- **WebSocket bridge** — the HTML side can open a real WebSocket and forward `open`, `message`, `close`, and `error` events to Python. Python can connect, send, and close sockets through the same bridge.

Midnight is shipped by `all-night` as the `night_midnight` module; it is not a separate `midnight` PyPI distribution.

`Midnight()` is the normal explicit constructor. `from night_midnight import midnight` remains a lazy convenience proxy, so importing the module no longer eagerly creates shared mutable state. Tests and applications that want an independent bridge can simply create their own `Midnight()` instance. `reset_default_midnight()` can replace the convenience instance during development or tests.

## Night templates + Midnight

Night's main `night.py` owns the generic `TemplateEngine`. Midnight does not implement a second parser: `MidnightTemplateEngine` subclasses the core engine and adds live DOM bindings on top.

```python
from night_midnight import midnight

@app.get("/")
def home():
    return midnight.render_template_string("""
      <h1>${{ title }}</h1>
      <p>${{ count }}</p>
      ${% if count > 0 %}<strong>Started</strong>${% endif %}
    """, title="Night", count=0)
```

Simple interpolations are emitted with `data-midnight-bind` markers. Python can update those bindings without re-rendering the page:

```python
midnight.set("count", 1)
```

File templates use the same engine through `midnight.render_template("page.html", ...)`. See [Templates](templates.md) for the shared syntax and extension model.

## HTML -> Python

```python
from night_midnight import midnight

@midnight.on("click", "#save")
def save(event):
    midnight.text("#status", "Saved from Python")

@midnight.on("submit", "#login", prevent_default=True)
async def login(event):
    form = event.get("form") or {}
    midnight.emit("login-result", {"user": form.get("user")})
```

The browser sends a small event snapshot rather than a live DOM object. Useful fields include `type`, `selector`, `target`, keyboard/mouse fields, and form data for `input`, `change`, and `submit` events.

For an application-defined event from HTML:

```html
<button onclick="midnight.emit('hello', {name: 'Night'})">Hello</button>
```

```python
@midnight.on_event("hello")
def hello(event):
    midnight.emit("hello-back", event["detail"])
```

## Python -> HTML

Midnight deliberately exposes structured DOM commands instead of arbitrary JavaScript evaluation:

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

HTML can listen for Python events:

```js
midnight.on("updated", detail => {
  console.log(detail.count)
})
```

If Browser Night cannot import Pyodide's `js` module, commands fall back to the current session outbox. If `nightMidnightPush()` exists but throws, that exception is deliberately propagated instead of being converted into a silent queue fallback.

## Multiple users and the trust boundary

Browser Night naturally isolates users because every browser tab owns its own Pyodide/Python runtime. A shared CPython server is different: one bridge can serve many clients, so Midnight separates mutable state and queued commands with `MidnightSession` objects selected by a `ContextVar`.

Handlers and subscriptions remain shared, while `midnight.state`, template bindings, and the Python->HTML outbox are session-local:

```python
@midnight.on_event("rename")
async def rename(event):
    midnight.set("name", event["name"])
    await do_something()
    midnight.text("#name", midnight.state["name"])
```

The untrusted/client-facing dispatch API intentionally has **no `session_id` argument**:

```python
commands = await midnight.dispatch_untrusted(event)
# `midnight.dispatch(event)` is the compatibility alias for the same safe shape.
```

A server adapter that needs to address a shared-process session must make an explicit trust transition:

```python
from night_midnight import trusted_session_id

session_id = trusted_session_id(authenticated_connection.id)
commands = await midnight.dispatch_trusted(session_id, event)

ws_commands = await midnight.dispatch_ws_trusted(session_id, ws_event)
```

`TrustedSessionId` is a distinct type for type checkers and the `*_trusted` method names make the boundary visible in code review. `trusted_session_id()` is an **assertion of trust, not authentication**: adapters must only call it with an identifier derived from authenticated connection/session context. Never wrap an ID copied directly from an arbitrary event payload.

The session binding survives `await` boundaries, so concurrent clients do not switch each other's active Midnight state. Trusted server code that needs to operate outside dispatch can bind a session explicitly:

```python
with midnight.trusted_session(session_id):
    midnight.set("unread", 3)
    midnight.emit("notification", {"count": 3})
```

Useful session APIs are:

```python
midnight.session_id
midnight.current_session
midnight.get_session(session_id)
midnight.session_ids()
midnight.drop_session(session_id)
```

Call `drop_session()` when a temporary authenticated connection/session is permanently closed if its in-memory state is no longer needed. The built-in store is process-local; multi-process or distributed applications should keep durable/shared application state in their normal database or session backend and use Midnight sessions for per-connection UI state.

## WebSocket transport

Python can ask the HTML side to create a WebSocket:

```python
@midnight.on_ws("open")
def opened(event):
    midnight.ws_send({"hello": "Night"}, socket_id=event["socket_id"])

@midnight.on_ws("message")
def message(event):
    print(event.get("data"), event.get("json"))

midnight.ws_connect("wss://example.com/socket", socket_id="chat")
```

Or HTML can create it directly:

```js
midnight.connect("wss://example.com/socket", {socketId: "chat"})
midnight.send({hello: "Night"}, "chat")
```

WebSocket lifecycle events are forwarded to `@midnight.on_ws(...)` handlers.

## Architecture

```text
HTML DOM events ─┐
                 ├─ midnight.js ─ postMessage ─ Pyodide ─ night_midnight.py
WebSocket events ┘                                  │
                                                   │ structured commands
                                                   ▼
HTML DOM / CustomEvent / WebSocket

Shared CPython server:
authenticated connection ID -> TrustedSessionId -> ContextVar
                            -> MidnightSession -> state + outbox
```

Midnight keeps the local DOM bridge separate from WebSocket so a Browser Night page does not need to create a network socket merely to communicate with the Python runtime in the same tab.
