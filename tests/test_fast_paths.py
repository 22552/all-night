import asyncio

import pytest

from night import MethodNotAllowed, Night, Request


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
    app = Night()

    @app.get("/hello")
    def hello():
        return "hi"

    route, params = app._match_method("/hello", "GET")
    assert route.endpoint is hello
    assert params == {}
    assert app._static_method_index["GET"]["/hello"] is route


def test_static_method_not_allowed_preserves_allow():
    app = Night()

    @app.get("/hello")
    def hello():
        return "hi"

    with pytest.raises(MethodNotAllowed) as exc:
        app._match_method("/hello", "POST")
    assert set(exc.value.allowed) == {"GET", "HEAD"}


def test_dynamic_routes_fall_back_and_convert_int_params():
    app = Night()

    @app.get("/users/<int:id>")
    def user(id: int):
        return {"id": id}

    route, params = app._match_method("/users/42", "GET")
    response = asyncio.run(app._call_endpoint(route.endpoint, _request("/users/42"), params))
    assert response.status == 200
    assert b'"id":42' in response.body


def test_multiple_dynamic_routes_select_and_convert_params():
    app = Night()

    @app.get("/users/<int:id>")
    def user(id: int):
        return {"kind": "user", "id": id}

    @app.get("/posts/<int:id>")
    def post(id: int):
        return {"kind": "post", "id": id}

    route, params = app._match_method("/posts/42", "GET")
    assert route.endpoint is post
    assert params == {"id": 42}
    response = asyncio.run(app._call_route(route, _request("/posts/42"), params))
    assert b'"kind":"post"' in response.body
    assert b'"id":42' in response.body


def test_request_injection_plan_is_compiled_at_registration():
    app = Night()

    @app.get("/method")
    def method(req: Request):
        return req.method

    assert method in app._endpoint_plans
    route, params = app._match_method("/method", "GET")
    response = asyncio.run(app._call_endpoint(route.endpoint, _request("/method"), params))
    assert response.body == b"GET"


def test_sync_async_classification_is_compiled_at_registration():
    app = Night()

    @app.get("/sync")
    def sync_handler():
        return "sync"

    @app.get("/async")
    async def async_handler():
        return "async"

    assert app._endpoint_plans[sync_handler].is_coro is False
    assert app._endpoint_plans[async_handler].is_coro is True


def test_mount_rebuilds_fast_index():
    from night import Router

    child = Router()

    @child.get("/ping")
    def ping():
        return "pong"

    app = Night()
    app.mount("/api", child)

    route, params = app._match_method("/api/ping", "GET")
    assert route.endpoint is ping
    assert params == {}


def test_complex_dynamic_routes_skip_unrelated_regex_buckets():
    app = Night()
    endpoints = []

    for index in range(80):
        def endpoint(a, b, _index=index):
            return str(_index)
        app.get(f"/group{index}/<a>/<b>", endpoint)
        endpoints.append(endpoint)

    target_route = next(
        route for route in app.routes
        if route.raw_path == "/group79/<a>/<b>"
    )

    class BombPattern:
        def match(self, _path):
            raise AssertionError("unrelated complex regex was evaluated")

    for route in app.routes:
        if route is not target_route and route.raw_path.startswith("/group"):
            route.pattern = BombPattern()

    route, params = app._match_method("/group79/one/two", "GET")
    assert route is target_route
    assert params == {"a": "one", "b": "two"}
    assert app._complex_prefix_index["GET"]["/group79/"] == [target_route]


def test_complex_dynamic_bucket_preserves_root_route_order():
    app = Night()

    @app.get("/<path:anything>")
    def catch_all(anything):
        return anything

    @app.get("/api/<left>/<right>")
    def specific(left, right):
        return left + right

    route, params = app._match_method("/api/one/two", "GET")
    assert route.endpoint is catch_all
    assert params == {"anything": "api/one/two"}


def test_mount_rebuilds_complex_dynamic_index():
    from night import Router

    child = Router()

    @child.get("/items/<left>/<right>")
    def item(left, right):
        return left + right

    app = Night()
    app.mount("/api", child)

    route, params = app._match_method("/api/items/a/b", "GET")
    assert route.endpoint is item
    assert params == {"left": "a", "right": "b"}
    assert route in app._complex_prefix_index["GET"]["/api/"]
