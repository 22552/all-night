import dataclasses
import json

from night import Night, Request


def test_decorator_explicit_and_chained_route_registration():
    app = Night()

    @app.get("/decorated")
    def decorated():
        return "decorated"

    def explicit():
        return "explicit"

    def direct():
        return "direct"

    def chained():
        return "chained"

    assert app.add_route("GET", "/explicit", explicit) is app
    assert app.get("/direct", direct) is app
    assert app.get("/chained", chained).add_route("GET", "/after-chain", explicit) is app

    with app.test_client() as client:
        assert client.get("/decorated").text == "decorated"
        assert client.get("/explicit").text == "explicit"
        assert client.get("/direct").text == "direct"
        assert client.get("/chained").text == "chained"
        assert client.get("/after-chain").text == "explicit"


def test_direct_post_body_model_and_multiple_methods():
    app = Night()

    @dataclasses.dataclass
    class Payload:
        value: int

    def body_handler(data: Payload):
        return {"value": data.value}

    def both():
        return "both"

    assert app.post("/body", body_handler, body=Payload) is app
    assert app.add_route(("GET", "POST"), "/both", both) is app

    with app.test_client() as client:
        response = client.post(
            "/body",
            data=json.dumps({"value": 7}),
            headers={"content-type": "application/json"},
        )
        assert response.get_json() == {"value": 7}
        assert client.get("/both").text == "both"
        assert client.post("/both").text == "both"


def test_request_handlers_keep_path_params_on_fast_invokers():
    app = Night()

    @app.get("/keyword/<int:user_id>")
    def keyword(user_id: int, *, req: Request):
        return {"user_id": user_id, "path": req.path, "params": req.path_params}

    @app.get("/positional/<int:user_id>")
    def positional(req: Request, user_id: int):
        return {"user_id": user_id, "path": req.path, "params": req.path_params}

    with app.test_client() as client:
        assert client.get("/keyword/11").get_json() == {
            "user_id": 11,
            "path": "/keyword/11",
            "params": {"user_id": 11},
        }
        assert client.get("/positional/12").get_json() == {
            "user_id": 12,
            "path": "/positional/12",
            "params": {"user_id": 12},
        }
