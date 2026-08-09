import asyncio

from night_midnight import (
    CompiledMidnight,
    MidnightWebSocketAdapter,
    js,
    read_midnight_js,
)


class FakeWebSocket:
    def __init__(self, messages):
        self.messages = list(messages)
        self.sent = []
        self.accepted = False

    async def accept(self):
        self.accepted = True

    async def receive_json(self):
        if not self.messages:
            raise ConnectionError("done")
        return self.messages.pop(0)

    async def send_json(self, data):
        self.sent.append(data)


def _compiled_midnight():
    midnight = CompiledMidnight()

    @midnight.on("click", "#plus")
    @midnight.compile
    def plus(event):
        value = midnight.get("#value")
        value.value = js.Number(value.value) + 1

    return midnight


def test_direct_runtime_uses_websocket_not_fetch():
    runtime = read_midnight_js()
    assert "new WebSocket" in runtime
    assert "connectTransport" in runtime
    assert "fetch(" not in runtime
    assert "compiled_install" in runtime
    assert "hybrid_server_set" in runtime


def test_adapter_sends_config_and_compiled_commands():
    midnight = _compiled_midnight()
    ws = FakeWebSocket(
        [
            {
                "type": "midnight-event",
                "event_id": 7,
                "event": {"type": "click", "selector": "#plus", "target": {"id": "plus"}},
            }
        ]
    )

    asyncio.run(MidnightWebSocketAdapter(midnight).serve(ws))

    assert ws.accepted is True
    assert ws.sent[0] == {
        "type": "midnight-config",
        "subscriptions": [
            {"event": "click", "selector": "#plus", "prevent_default": False}
        ],
    }
    response = ws.sent[1]
    assert response["type"] == "midnight-commands"
    assert response["event_id"] == 7
    command = response["commands"][0]
    assert command["op"] == "compiled_install"
    assert command["event"] == "click"
    assert command["selector"] == "#plus"
    assert command["exclusive"] is True
    assert command["execute_now"] is True


def test_compile_install_is_per_websocket_session():
    midnight = _compiled_midnight()
    payload = {
        "type": "midnight-event",
        "event_id": 1,
        "event": {"type": "click", "selector": "#plus"},
    }

    first = FakeWebSocket([payload])
    second = FakeWebSocket([payload])
    asyncio.run(MidnightWebSocketAdapter(midnight).serve(first))
    asyncio.run(MidnightWebSocketAdapter(midnight).serve(second))

    assert first.sent[1]["commands"][0]["op"] == "compiled_install"
    assert second.sent[1]["commands"][0]["op"] == "compiled_install"


def test_compiled_pair_is_not_exclusive_when_server_handler_shares_event():
    midnight = CompiledMidnight()

    @midnight.on("click", "#plus")
    @midnight.compile
    def compiled(event):
        value = midnight.get("#value")
        value.value = js.Number(value.value) + 1

    @midnight.on("click", "#plus")
    def server(event):
        midnight.text("#status", "server")

    commands = asyncio.run(
        midnight.dispatch_untrusted({"type": "click", "selector": "#plus"})
    )
    install = next(command for command in commands if command["op"] == "compiled_install")
    assert install["exclusive"] is False
