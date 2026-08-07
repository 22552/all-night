import asyncio

from night import Night


def test_test_client_reuses_event_loop_and_survives_close():
    app = Night()
    loops = []

    @app.get("/loop")
    def loop_id():
        loops.append(id(asyncio.get_running_loop()))
        return {"ok": True}

    client = app.test_client()
    assert client.get("/loop").status_code == 200
    assert client.get("/loop").status_code == 200
    assert loops[0] == loops[1]

    client.close()
    assert client.get("/loop").status_code == 200
    assert loops[2] != loops[1]
    client.close()


def test_test_client_context_manager_closes_runner():
    app = Night()

    @app.get("/")
    def index():
        return "ok"

    with app.test_client() as client:
        assert client.get("/").text == "ok"
        runner = client._runner
        assert runner is not None

    assert client._runner is None

    # A closed client can be reused; it lazily creates a fresh Runner.
    assert client.get("/").text == "ok"
    assert client._runner is not None
    assert client._runner is not runner
    client.close()
