import asyncio

from night_midnight import HybridMidnight, js


def test_plain_python_value_is_set_directly():
    midnight = HybridMidnight()
    field = midnight.get("#field")

    field.value = len([1, 2, 3])

    assert midnight.drain() == [
        {"op": "dom_set", "selector": "#field", "property": "value", "value": 3}
    ]


def test_js_marker_keeps_expression_in_browser():
    midnight = HybridMidnight()
    field = midnight.get("#field")

    field.value = js.Number(field.value) + 1

    commands = midnight.drain()
    assert len(commands) == 1
    command = commands[0]
    assert command["op"] == "hybrid_client_set"
    assert command["selector"] == "#field"
    assert command["property"] == "value"
    assert command["expr"]["kind"] == "binary"
    assert command["expr"]["op"] == "add"
    assert command["expr"]["left"]["kind"] == "call"
    assert command["expr"]["left"]["callee"] == {"kind": "js_ref", "path": ["Number"]}
    assert command["expr"]["left"]["args"] == [
        {"kind": "dom", "selector": "#field", "property": "value"}
    ]


def test_normal_operator_roundtrips_through_python():
    midnight = HybridMidnight()
    field = midnight.get("#field")

    field.value = field.value + "!"

    commands = midnight.drain()
    assert len(commands) == 1
    request = commands[0]
    assert request["op"] == "hybrid_server_set"
    assert request["reads"] == [{"selector": "#field", "property": "value"}]

    result = asyncio.run(
        midnight.dispatch_untrusted(
            {
                "type": "custom:__hybrid_result",
                "selector": None,
                "detail": {"request_id": request["request_id"], "values": ["hello"]},
            }
        )
    )
    assert result == [
        {"op": "dom_set", "selector": "#field", "property": "value", "value": "hello!"}
    ]


def test_python_semantics_are_not_silently_changed_to_js():
    midnight = HybridMidnight()
    field = midnight.get("#field")
    field.value = field.value + 1
    request = midnight.drain()[0]

    result = asyncio.run(
        midnight.dispatch_untrusted(
            {
                "type": "custom:__hybrid_result",
                "selector": None,
                "detail": {"request_id": request["request_id"], "values": ["1"]},
            }
        )
    )

    assert result[0]["op"] == "hybrid_error"
    assert result[0]["error_type"] == "TypeError"
