import asyncio

from night import Night


def test_websocket_accept_consumes_connect_before_accepting():
    app = Night()

    @app.websocket("/ws")
    async def echo(ws):
        await ws.accept()
        message = await ws.receive_text()
        await ws.send_text(message)

    events = [
        {"type": "websocket.connect"},
        {"type": "websocket.receive", "text": "hello"},
    ]
    sent = []

    async def receive():
        return events.pop(0)

    async def send(event):
        sent.append(event)

    scope = {"type": "websocket", "path": "/ws", "headers": []}
    asyncio.run(app(scope, receive, send))

    assert sent == [
        {"type": "websocket.accept"},
        {"type": "websocket.send", "text": "hello"},
    ]


def test_websocket_accept_handles_disconnect_before_handshake():
    app = Night()

    @app.websocket("/ws")
    async def endpoint(ws):
        await ws.accept()

    async def receive():
        return {"type": "websocket.disconnect", "code": 1001}

    sent = []

    async def send(event):
        sent.append(event)

    scope = {"type": "websocket", "path": "/ws", "headers": []}
    asyncio.run(app(scope, receive, send))
    assert sent == []
