import asyncio
import json
import sys
import types

import pytest

from night_midnight import (
    Midnight,
    get_default_midnight,
    reset_default_midnight,
    trusted_session_id,
)


def test_dom_subscription_and_dispatch():
    bridge = Midnight()
    seen = []

    @bridge.on("click", "#save", prevent_default=True)
    def save(event):
        seen.append(event["target"]["id"])
        bridge.text("#status", "saved")

    assert bridge.subscriptions() == [
        {"event": "click", "selector": "#save", "prevent_default": True}
    ]

    commands = asyncio.run(
        bridge.dispatch(
            {
                "type": "click",
                "selector": "#save",
                "target": {"id": "save"},
            }
        )
    )
    assert seen == ["save"]
    assert commands == [{"op": "text", "selector": "#status", "value": "saved"}]


def test_subscription_dedup_uses_keyed_index():
    bridge = Midnight()

    @bridge.on("click", "#same", prevent_default=True)
    def first(event):
        pass

    @bridge.on("click", "#same", prevent_default=True)
    def second(event):
        pass

    assert bridge.subscriptions() == [
        {"event": "click", "selector": "#same", "prevent_default": True}
    ]


def test_custom_event_and_async_handler():
    bridge = Midnight()

    @bridge.on_event("hello")
    async def hello(event):
        await asyncio.sleep(0)
        bridge.emit("reply", {"hello": event["detail"]["name"]})

    commands = asyncio.run(
        bridge.dispatch({"type": "custom:hello", "selector": None, "detail": {"name": "Night"}})
    )
    assert commands == [{"op": "emit", "name": "reply", "detail": {"hello": "Night"}}]


def test_websocket_commands_and_dispatch_json():
    bridge = Midnight()
    messages = []

    @bridge.on_ws("message")
    def message(event):
        messages.append(event["data"])
        bridge.ws_send({"pong": True}, socket_id=event["socket_id"])

    result = asyncio.run(
        bridge.dispatch_ws_json(
            json.dumps({"type": "message", "socket_id": "chat", "data": "ping"})
        )
    )
    assert messages == ["ping"]
    assert json.loads(result) == [
        {"op": "ws_send", "socket_id": "chat", "data": {"pong": True}}
    ]


def test_python_to_html_helpers_queue_outside_browser():
    bridge = Midnight()
    bridge.value("#name", "Ada")
    bridge.attr("#name", "aria-label", "Name")
    bridge.add_class("#name", "ready", "active")
    bridge.remove_class("#name", "hidden")
    bridge.focus("#name")
    bridge.ws_connect("wss://example.invalid/socket", socket_id="demo", protocols=["json"])
    bridge.ws_close(socket_id="demo", code=1000, reason="done")

    ops = [item["op"] for item in bridge.drain()]
    assert ops == [
        "value",
        "attr",
        "class_add",
        "class_remove",
        "focus",
        "ws_connect",
        "ws_close",
    ]


def test_browser_bridge_exceptions_are_not_silenced(monkeypatch):
    bridge = Midnight()
    fake_js = types.ModuleType("js")

    def broken_push(payload):
        raise RuntimeError("broken JS bridge")

    fake_js.nightMidnightPush = broken_push
    monkeypatch.setitem(sys.modules, "js", fake_js)

    with pytest.raises(RuntimeError, match="broken JS bridge"):
        bridge.text("#status", "boom")


def test_session_context_isolates_state_and_outbox():
    bridge = Midnight()
    alice_id = trusted_session_id("alice")
    bob_id = trusted_session_id("bob")
    assert bridge.session_id == "default"

    with bridge.trusted_session(alice_id):
        assert bridge.session_id == "alice"
        bridge.set("count", 1)
        bridge.text("#who", "Alice")
        assert bridge.state == {"count": 1}

    assert bridge.session_id == "default"

    with bridge.trusted_session(bob_id):
        bridge.set("count", 9)
        bridge.text("#who", "Bob")
        assert bridge.state == {"count": 9}

    assert bridge.get_session(alice_id).state == {"count": 1}
    assert bridge.get_session(bob_id).state == {"count": 9}

    with bridge.trusted_session(alice_id):
        assert bridge.drain() == [
            {"op": "bind", "name": "count", "value": 1},
            {"op": "text", "selector": "#who", "value": "Alice"},
        ]

    with bridge.trusted_session(bob_id):
        assert bridge.drain() == [
            {"op": "bind", "name": "count", "value": 9},
            {"op": "text", "selector": "#who", "value": "Bob"},
        ]


def test_untrusted_dispatch_cannot_choose_session_id():
    bridge = Midnight()
    event = {"type": "custom:none", "selector": None}

    with pytest.raises(TypeError):
        asyncio.run(bridge.dispatch(event, session_id="victim"))


def test_trusted_dispatch_survives_async_interleaving():
    bridge = Midnight()

    @bridge.on_event("identify")
    async def identify(event):
        bridge.set("name", event["name"])
        await asyncio.sleep(0)
        bridge.text("#name", bridge.state["name"])

    async def run():
        return await asyncio.gather(
            bridge.dispatch_trusted(
                trusted_session_id("alice"),
                {"type": "custom:identify", "selector": None, "name": "Alice"},
            ),
            bridge.dispatch_trusted(
                trusted_session_id("bob"),
                {"type": "custom:identify", "selector": None, "name": "Bob"},
            ),
        )

    alice, bob = asyncio.run(run())

    assert alice == [
        {"op": "bind", "name": "name", "value": "Alice"},
        {"op": "text", "selector": "#name", "value": "Alice"},
    ]
    assert bob == [
        {"op": "bind", "name": "name", "value": "Bob"},
        {"op": "text", "selector": "#name", "value": "Bob"},
    ]
    assert bridge.get_session(trusted_session_id("alice")).state["name"] == "Alice"
    assert bridge.get_session(trusted_session_id("bob")).state["name"] == "Bob"
    assert bridge.session_id == "default"


def test_drop_session_discards_server_side_state():
    bridge = Midnight()
    session_id = trusted_session_id("temporary")
    with bridge.trusted_session(session_id):
        bridge.set("value", 42)

    assert "temporary" in bridge.session_ids()
    assert bridge.drop_session(session_id) is True
    assert "temporary" not in bridge.session_ids()
    assert bridge.drop_session(session_id) is False


def test_default_midnight_is_lazy_resettable_convenience_instance():
    first = reset_default_midnight()
    assert get_default_midnight() is first

    second = reset_default_midnight()
    assert second is not first
    assert get_default_midnight() is second
