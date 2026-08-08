# Midnight

Midnight is Browser Night's bidirectional bridge between Python and the rendered HTML page.

It has two transports:

- **Local DOM bridge** — browser events are captured in JavaScript and dispatched directly into Python running in Pyodide. This uses `postMessage`, not a loopback WebSocket, so local UI events stay lightweight.
- **WebSocket bridge** — the HTML side can open a real WebSocket and forward `open`, `message`, `close`, and `error` events to Python. Python can connect, send, and close sockets through the same bridge.

Midnight is shipped by `all-night` as the `night_midnight` module; it is not a separate `midnight` PyPI distribution.

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
```

Midnight keeps the local DOM bridge separate from WebSocket so a Browser Night page does not need to create a network socket merely to communicate with the Python runtime in the same tab.
