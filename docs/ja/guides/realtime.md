# リアルタイム

## WebSocket

```python
@app.websocket("/chat")
async def chat(ws):
    await ws.accept()
    message = await ws.receive_json()
    await ws.send_json({"echo": message})
    await ws.close()
```

テキスト、バイト列、JSONの送受信をサポートします。

## SSE

```python
from night import sse

@app.get("/events")
async def events():
    async def source():
        yield {"event": "status", "data": {"ready": True}}
    return sse(source())
```

一般的なストリーミングには `stream()` を使います。

## Lifespan

`@app.on_startup` と `@app.on_shutdown` はASGI lifespanイベントで実行されます。アプリケーションが所有する接続などの開始・終了に使います。


