# Midnight components and hot reload

Midnight can group reusable UI behavior behind a component scope and can run a dependency-free development watcher over Night's existing WebSocket support.

## Scoped components

`Component` adds two kinds of scope without creating a second event system:

- a CSS root selector for DOM events and updates;
- a logical namespace for custom events and live template bindings.

```python
from night_midnight import midnight
from night_midnight_component import Component

profile = Component("#profile", name="profile", bridge=midnight)

@profile.on("click", ".close")
def close(event):
    profile.remove_class("&", "open")
    profile.set("visible", False)
    profile.emit("closed")
```

The local selector `.close` is registered as `#profile .close`. `&` means the component root itself, so `& > header` becomes `#profile > header`.

Bindings and custom events are namespaced too:

```python
profile.set("visible", True)      # binding: profile.visible
profile.emit("closed")           # custom event: profile:closed

@profile.on_event("closed")
def closed(event):
    ...
```

This lets several instances reuse the same local selector names without collisions:

```python
left = Component("#left-tabs", name="left")
right = Component("#right-tabs", name="right")
```

`Component` delegates to the public `Midnight` API, so session isolation, Browser Night direct bridging, and queued server adapters keep the same semantics.

## Dependency-free hot reload

`HotReload` lives in `night_midnight_dev` so production Midnight imports do not start development watcher machinery. It uses:

- Night's normal `@app.websocket(...)` support;
- `os.stat()` snapshots for modification detection;
- `asyncio.sleep()` polling;
- no `watchdog` or other runtime dependency.

Full-page reload:

```python
from night import Night
from night_midnight_dev import HotReload

app = Night()
dev = HotReload(app, ["app.py", "templates"], interval=0.35)

@app.get("/")
def home():
    return f"""
    <main>Hello</main>
    {dev.client_script()}
    """
```

The client opens `/__midnight_reload` as a WebSocket. When any watched file's `(mtime_ns, size)` snapshot changes, the server broadcasts `{"type":"reload"}` and the browser calls `location.reload()`.

Directories are scanned recursively. `.git`, `__pycache__`, `.venv`, `venv`, and `node_modules` are ignored.

## Component-only refresh

For a UI region that can be rendered independently, the watcher can replace only that region's HTML:

```python
card = Component("#card", name="card")

def render_card():
    return "<strong>fresh card</strong>"

card_reload = HotReload(
    app,
    ["components/card.py", "templates/card.html"],
    mode="component",
    selector=card.root,
    render=render_card,
)
```

`render` may be synchronous or asynchronous. A changed file produces a `component` WebSocket message and the dev client updates `innerHTML` for matching elements instead of reloading the page.

Hot reload is a development helper, not a production state synchronization protocol. Long-lived application state should continue to use normal Night/Midnight sessions, WebSocket APIs, or application storage.
