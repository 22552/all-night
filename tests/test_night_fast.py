import asyncio

import pytest

from night import MethodNotAllowed, Request
from night_fast import FastNight


async def _empty_receive():
    return {"type": "http.request", "body": b"", "more_body": False}


def _request(path="/", method="GET"):
    return Request(
        scope={
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "server": ("test", 80),
            "client": None,
        },
        receive=_empty_receive,
        send=None,
    )


def test_static_routes_use_method_path_index():
    app = FastNight()

    @app.get("/hello")
    def hello():
        return "hi"

    route, params = app._match_method("/hello", "GET")
    assert route.endpoint is hello
    assert params == {}
    assert app._fast_static["GET"]["/hello"] is route


def test_static_method_not_allowed_preserves_allow():
    app = FastNight()

    @app.get("/hello")
    def hello():
        return "hi"

    with pytest.raises(MethodNotAllowed) as exc:
        app._match_method("/hello", "POST")
    assert set(exc.value.allowed) == {"GET", "HEAD"}


def test_dynamic_routes_fall_back_and_convert_int_params():
    app = FastNight()

    @app.get("/users/<int:id>")
    def user(id: int):
        return {"id": id}

    route, params = app._match_method("/users/42", "GET")
    response = asyncio.run(app._call_endpoint(route.endpoint, _request("/users/42"), params))
    assert response.status == 200
    assert b'"id":42' in response.body


def test_request_injection_plan_is_compiled_at_registration():
    app = FastNight()

    @app.get("/method")
    def method(req: Request):
        return req.method

    assert method in app._endpoint_plans
    route, params = app._match_method("/method", "GET")
    response = asyncio.run(app._call_endpoint(route.endpoint, _request("/method"), params))
    assert response.body == b"GET"


def test_mount_rebuilds_fast_index():
    from night import Router

    child = Router()

    @child.get("/ping")
    def ping():
        return "pong"

    app = FastNight()
    app.mount("/api", child)

    route, params = app._match_method("/api/ping", "GET")
    assert route.endpoint is ping
    assert params == {}
