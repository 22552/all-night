from night_midnight import Midnight, trusted_session_id


def test_midnight_caps_session_count_with_lru_eviction():
    now = [0.0]
    midnight = Midnight(max_sessions=3, session_ttl=0, clock=lambda: now[0])

    for name in ("a", "b", "c", "d"):
        now[0] += 1
        with midnight.trusted_session(trusted_session_id(name)):
            midnight.state["name"] = name

    ids = midnight.session_ids()
    assert "default" in ids
    assert len(ids) <= 3
    assert "d" in ids
    assert "a" not in ids


def test_midnight_prunes_expired_sessions():
    now = [0.0]
    midnight = Midnight(max_sessions=10, session_ttl=5, clock=lambda: now[0])

    with midnight.trusted_session(trusted_session_id("old")):
        midnight.state["x"] = 1

    now[0] = 10.0
    with midnight.trusted_session(trusted_session_id("new")):
        midnight.state["x"] = 2

    midnight.prune_sessions()
    assert "old" not in midnight.session_ids()
    assert "new" in midnight.session_ids()


def test_midnight_caps_outbox():
    midnight = Midnight(max_outbox=3)
    for value in range(6):
        midnight.text("#x", value)

    commands = midnight.drain()
    assert [item["value"] for item in commands] == ["3", "4", "5"]


def test_default_session_is_preserved():
    midnight = Midnight(max_sessions=1, session_ttl=0)
    with midnight.trusted_session(trusted_session_id("temporary")):
        midnight.text("#x", "hello")
    assert "default" in midnight.session_ids()
