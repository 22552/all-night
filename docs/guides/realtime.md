# Realtime and application lifecycle

## WebSocket

```python
@app.websocket("/chat")
async def chat(ws):
    await ws.accept()
    message = await ws.receive_json()
    await ws.send_json({"echo": message})
    await ws.close()
```

`WebSocket` supports text, bytes, and JSON send/receive methods. Unhandled endpoint failures close the connection with an internal-error status.

## Server-sent events

```python
from night import sse

@app.get("/events")
async def events():
    async def source():
        yield {"event": "status", "data": {"ready": True}}
    return sse(source())
```

Use `stream()` for general streaming response bodies.

## Lifespan

```python
@app.on_startup
async def connect():
    ...

@app.on_shutdown
async def disconnect():
    ...
```

These hooks run from ASGI lifespan events and are appropriate for opening and closing application-owned resources.


