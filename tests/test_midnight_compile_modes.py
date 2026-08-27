import asyncio
import json

from night_midnight import (
    CompiledMidnight,
    MidnightWebSocketAdapter,
    get_default_midnight,
    js,
    reset_default_midnight,
)


def test_default_midnight_exposes_compile_modes():
    current = reset_default_midnight()
    assert isinstance(current, CompiledMidnight)
    assert get_default_midnight() is current
    assert callable(current.server)
    assert callable(current.compile)
    assert callable(current.static)
    assert callable(current.full_compile)


def test_server_mode_runs_for_every_server_event():
    midnight = CompiledMidnight()
    calls = []

    @midnight.on("click", "#server")
    @midnight.server
    def handler(event):
        calls.append(event["value"])

    asyncio.run(
        midnight.dispatch_untrusted(
            {"type": "click", "selector": "#server", "value": 1}
        )
    )
    asyncio.run(
        midnight.dispatch_untrusted(
            {"type": "click", "selector": "#server", "value": 2}
        )
    )

    assert calls == [1, 2]


def test_static_mode_traces_at_registration_and_queues_ir_before_events():
    midnight = CompiledMidnight()
    calls = []

    @midnight.on("click", "#plus")
    @midnight.static
    def plus(event):
        calls.append("trace")
        field = midnight.get("#count")
        field.value = js.Number(field.value) + 1

    assert calls == ["trace"]
    programs = midnight.client_programs()
    assert len(programs) == 1
    assert programs[0]["op"] == "compiled_install"
    assert programs[0]["mode"] == "Static"
    assert programs[0]["execute_now"] is False
    assert programs[0]["exclusive"] is True
    assert programs[0]["program"][0]["op"] == "dom_set_expr"

    json.loads(midnight.subscriptions_json())
    queued = midnight.drain()
    assert len(queued) == 1
    assert queued[0]["op"] == "compiled_install"
    assert queued[0]["mode"] == "Static"

    commands = asyncio.run(
        midnight.dispatch_untrusted({"type": "click", "selector": "#plus"})
    )
    assert commands == []
    assert calls == ["trace"]


def test_full_compile_routes_to_registered_local_python_handler():
    midnight = CompiledMidnight()
    calls = []

    @midnight.on("click", "#hello")
    @midnight.full_compile
    def hello(event):
        calls.append(event["name"])
        midnight.text("#result", event["name"].upper())

    program = midnight.client_programs()[0]
    assert program["op"] == "full_compiled_install"
    assert program["mode"] == "FullCompile"
    assert program["exclusive"] is True

    commands = asyncio.run(
        midnight.dispatch_untrusted(
            {
                "type": "custom:__full_compile",
                "selector": None,
                "detail": {
                    "handler_id": program["handler_id"],
                    "event": {"name": "night"},
                },
            }
        )
    )

    assert calls == ["night"]
    assert commands == [
        {"op": "text", "selector": "#result", "value": "NIGHT"}
    ]


def test_full_compile_falls_back_to_server_when_local_runtime_did_not_run_it():
    midnight = CompiledMidnight()
    calls = []

    @midnight.on("click", "#fallback")
    @midnight.full_compile
    def handler(event):
        calls.append(event["value"])

    program = midnight.client_programs()[0]

    asyncio.run(
        midnight.dispatch_untrusted(
            {"type": "click", "selector": "#fallback", "value": "server"}
        )
    )
    asyncio.run(
        midnight.dispatch_untrusted(
            {
                "type": "click",
                "selector": "#fallback",
                "value": "duplicate",
                "__midnight_local_handlers": [program["handler_id"]],
            }
        )
    )

    assert calls == ["server"]


def test_websocket_adapter_preinstalls_static_programs():
    midnight = CompiledMidnight()

    @midnight.on("click", "#plus")
    @midnight.static
    def plus(event):
        field = midnight.get("#count")
        field.value = js.Number(field.value) + 1

    class Socket:
        def __init__(self):
            self.messages = []

        async def accept(self):
            return None

        async def send_json(self, message):
            self.messages.append(message)

        async def receive_json(self):
            raise ConnectionError

    socket = Socket()
    asyncio.run(MidnightWebSocketAdapter(midnight).serve(socket))

    assert socket.messages[0]["type"] == "midnight-config"
    assert socket.messages[1]["type"] == "midnight-commands"
    assert socket.messages[1]["event_id"] == 0
    assert socket.messages[1]["commands"][0]["mode"] == "Static"
