import asyncio
import pathlib

from night_midnight import Midnight
from night_midnight_component import Component
from night_midnight_dev import HotReload


class FakeApp:
    def __init__(self):
        self.websocket_path = None
        self.websocket_handler = None

    def websocket(self, path):
        self.websocket_path = path

        def decorator(fn):
            self.websocket_handler = fn
            return fn

        return decorator


def test_component_scopes_selectors_bindings_and_events():
    bridge = Midnight()
    modal = Component("#profile", name="profile", bridge=bridge)

    @modal.on("click", ".close")
    def close(event):
        modal.text(".status", "closed")
        modal.set("open", False)
        modal.emit("closed", {"ok": True})

    @modal.on_event("closed")
    def closed(event):
        modal.add_class("&", "done")

    assert modal.selector(".close") == "#profile .close"
    assert modal.selector("& > header") == "#profile > header"
    assert modal.binding("open") == "profile.open"
    assert modal.event_name("closed") == "profile:closed"

    commands = asyncio.run(
        bridge.dispatch(
            {
                "type": "click",
                "selector": "#profile .close",
                "target": {"id": None},
            }
        )
    )
    assert commands == [
        {"op": "text", "selector": "#profile .status", "value": "closed"},
        {"op": "bind", "name": "profile.open", "value": False},
        {"op": "emit", "name": "profile:closed", "detail": {"ok": True}},
    ]

    commands = asyncio.run(
        bridge.dispatch(
            {
                "type": "custom:profile:closed",
                "selector": None,
                "detail": {"ok": True},
            }
        )
    )
    assert commands == [
        {"op": "class_add", "selector": "#profile", "names": ["done"]}
    ]


def test_two_component_instances_do_not_share_selectors_or_bindings():
    bridge = Midnight()
    left = Component("#left", name="left", bridge=bridge)
    right = Component("#right", name="right", bridge=bridge)

    left.set("active", True)
    right.set("active", False)

    assert bridge.drain() == [
        {"op": "bind", "name": "left.active", "value": True},
        {"op": "bind", "name": "right.active", "value": False},
    ]


def test_hot_reload_detects_stat_changes(tmp_path: pathlib.Path):
    watched = tmp_path / "app.py"
    watched.write_text("value = 1\n", encoding="utf-8")
    app = FakeApp()
    reload = HotReload(app, [watched], interval=0.01)

    assert app.websocket_path == "/__midnight_reload"
    assert app.websocket_handler is not None
    assert reload.changed() is False

    watched.write_text("value = 200\n", encoding="utf-8")
    assert reload.changed() is True
    assert reload.changed() is False


def test_hot_reload_messages_and_client_script():
    app = FakeApp()
    reload = HotReload(app, [], mode="reload")
    assert asyncio.run(reload._message()) == {"type": "reload"}
    script = reload.client_script()
    assert "new WebSocket" in script
    assert "location.reload()" in script

    component = HotReload(
        FakeApp(),
        [],
        mode="component",
        selector="#card",
        render=lambda: "<b>fresh</b>",
    )
    assert asyncio.run(component._message()) == {
        "type": "component",
        "selector": "#card",
        "html": "<b>fresh</b>",
    }


def test_hot_reload_component_mode_accepts_async_renderer():
    async def render():
        await asyncio.sleep(0)
        return "<span>async</span>"

    reload = HotReload(
        FakeApp(), [], mode="component", selector=".widget", render=render
    )
    assert asyncio.run(reload._message())["html"] == "<span>async</span>"
