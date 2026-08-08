# Midnight

Midnight is Browser Night's bidirectional bridge between Python and the rendered HTML page.

It has two transports:

- **Local DOM bridge** — browser events are captured in JavaScript and dispatched directly into Python running in Pyodide. This uses `postMessage`, not a loopback WebSocket, so local UI events stay lightweight.
- **WebSocket bridge** — the HTML side can open a real WebSocket and forward `open`, `message`, `close`, and `error` events to Python. Python can connect, send, and close sockets through the same bridge.

Midnight is shipped by `all-night` as the `night_midnight` module; it is not a separate `midnight` PyPI distribution.

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

## Multiple users and server sessions

Browser Night naturally isolates users because every browser tab owns its own Pyodide/Python runtime. A shared CPython server is different: one `midnight` object can serve many clients, so Midnight separates mutable state and queued commands with `MidnightSession` objects selected by a `ContextVar`.

Handlers and subscriptions remain global, while `midnight.state`, template bindings, and the Python->HTML outbox are session-local:

```python
@midnight.on_event("rename")
async def rename(event):
    midnight.set("name", event["name"])
    await do_something()
    midnight.text("#name", midnight.state["name"])
```

A server adapter supplies a stable session or connection ID when dispatching an event:

```python
commands = await midnight.dispatch(
    event,
    session_id=trusted_connection_id,
)

ws_commands = await midnight.dispatch_ws(
    ws_event,
    session_id=trusted_connection_id,
)
```

The session binding survives `await` boundaries, so concurrent clients do not switch each other's active Midnight state. Code that needs to perform work outside a dispatch can bind a session explicitly:

```python
with midnight.session(user_id):
    midnight.set("unread", 3)
    midnight.emit("notification", {"count": 3})
```

Useful session APIs are:

```python
midnight.session_id
midnight.current_session
midnight.get_session("alice")
midnight.session_ids()
midnight.drop_session("alice")
```

Call `drop_session()` when a temporary connection/session is permanently closed if its in-memory state is no longer needed. The built-in store is process-local; multi-process or distributed applications should keep durable/shared application state in their normal database or session backend and use Midnight sessions for per-connection UI state.

A server must derive `session_id` from trusted connection/authentication context. Do not let an arbitrary browser event choose another user's Midnight session ID.

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
connection/session ID -> ContextVar -> MidnightSession -> state + outbox
```

Midnight keeps the local DOM bridge separate from WebSocket so a Browser Night page does not need to create a network socket merely to communicate with the Python runtime in the same tab.
