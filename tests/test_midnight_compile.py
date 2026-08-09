import asyncio

import pytest

from night_midnight import CompiledMidnight, MidnightCompileError, js


def test_compile_installs_client_program_on_first_event():
    midnight = CompiledMidnight()

    @midnight.on("click", "#plus")
    @midnight.compile
    def plus(event):
        field = midnight.get("#count")
        field.value = js.Number(field.value) + 1

    commands = asyncio.run(
        midnight.dispatch_untrusted({"type": "click", "selector": "#plus"})
    )

    assert len(commands) == 1
    install = commands[0]
    assert install["op"] == "compiled_install"
    assert install["event"] == "click"
    assert install["selector"] == "#plus"
    assert install["execute_now"] is True
    assert install["program"][0]["op"] == "dom_set_expr"
    assert install["program"][0]["selector"] == "#count"


def test_compile_wrapper_does_not_retrace_after_install():
    midnight = CompiledMidnight()
    calls = []

    @midnight.on("click", "#plus")
    @midnight.compile
    def plus(event):
        calls.append("trace")
        field = midnight.get("#count")
        field.value = js.Number(field.value) + 1

    asyncio.run(midnight.dispatch_untrusted({"type": "click", "selector": "#plus"}))
    assert calls == ["trace"]

    commands = asyncio.run(midnight.dispatch_untrusted({"type": "click", "selector": "#plus"}))
    assert calls == ["trace"]
    assert commands == []


def test_event_values_stay_symbolic_in_program():
    midnight = CompiledMidnight()

    @midnight.on("keydown", "#name")
    @midnight.compile
    def key(event):
        field = midnight.get("#last-key")
        field.value = js.String(event["key"])

    install = asyncio.run(
        midnight.dispatch_untrusted({"type": "keydown", "selector": "#name", "key": "A"})
    )[0]

    event_node = install["program"][0]["expr"]["args"][0]
    assert event_node == {"kind": "event", "path": ["key"]}


def test_server_roundtrip_expression_is_rejected_inside_compile():
    midnight = CompiledMidnight()

    @midnight.on("click", "#bad")
    @midnight.compile
    def bad(event):
        field = midnight.get("#field")
        field.value = field.value + "!"

    with pytest.raises(MidnightCompileError):
        asyncio.run(midnight.dispatch_untrusted({"type": "click", "selector": "#bad"}))
