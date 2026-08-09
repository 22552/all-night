import asyncio

from night_midnight import read_midnight_js
from night_midnight_scope import F, G, Q, S, ScopedMidnight, match_filter


def test_filter_ast_is_serializable_and_matches_scopes():
    expr = (F.org_id == "acme") & (G.document_id == 42) & S.id.exists()
    node = expr.to_dict()
    scopes = {
        "F": {"org_id": "acme"},
        "G": {"document_id": 42},
        "S": {"id": "socket-1"},
        "Q": {},
    }
    assert match_filter(node, scopes) is True
    scopes["F"]["org_id"] = "other"
    assert match_filter(node, scopes) is False


def test_complex_filter_ops():
    expr = (
        (F.role.in_(["admin", "owner"]))
        & (F.age >= 13)
        & ~(Q.suspended == True)
        & G.tags.contains("night")
    )
    scopes = {
        "F": {"role": "admin", "age": 14},
        "G": {"tags": ["night", "python"]},
        "S": {},
        "Q": {"suspended": False},
    }
    assert match_filter(expr.to_dict(), scopes) is True


def test_g_survives_reconnect_but_s_resets():
    midnight = ScopedMidnight()

    async def sink(_message):
        return None

    first = midnight._register_connection(
        connection_id="socket-a",
        tab_id="tab-1",
        send=sink,
        F_values={"user_id": "u1"},
    )
    with midnight.connection("socket-a"):
        midnight.G.document_id = 42
        midnight.S.cursor = 10

    midnight._unregister_connection("socket-a")
    second = midnight._register_connection(
        connection_id="socket-b",
        tab_id="tab-1",
        send=sink,
        F_values={"user_id": "u1"},
    )

    assert second.scopes["G"]["document_id"] == 42
    assert second.scopes["G"]["id"] == "tab-1"
    assert second.scopes["S"] == {"id": "socket-b"}
    assert "cursor" not in second.scopes["S"]


def test_to_kwargs_are_f_scope_shortcut_and_broadcast_filters():
    midnight = ScopedMidnight()
    received_a = []
    received_b = []

    async def send_a(message):
        received_a.append(message)

    async def send_b(message):
        received_b.append(message)

    midnight._register_connection(
        connection_id="a",
        tab_id="tab-a",
        send=send_a,
        F_values={"org_id": "acme", "role": "admin"},
    )
    midnight._register_connection(
        connection_id="b",
        tab_id="tab-b",
        send=send_b,
        F_values={"org_id": "other", "role": "admin"},
    )

    count = asyncio.run(midnight.to(org_id="acme").text("#notice", "hello"))
    assert count == 1
    assert received_a[0]["commands"] == [
        {"op": "text", "selector": "#notice", "value": "hello"}
    ]
    assert received_b == []


def test_runtime_keeps_tab_id_in_session_storage_and_event_envelope():
    runtime = read_midnight_js()
    assert 'sessionStorage.getItem(key)' in runtime
    assert 'sessionStorage.setItem(key, value)' in runtime
    assert 'tab_id: state.tabId' in runtime
