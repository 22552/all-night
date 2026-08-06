#!/usr/bin/env python3
"""Routing/dispatch microbenchmarks for Night plus framework comparisons.

Run with:
    python benchmarks/fast_path.py

Two suites are reported:
1. Night hot-path dispatch: router match + endpoint call, without network/server I/O.
2. Public in-process framework clients for Night, Flask, Robyn, Bottle,
   FastAPI, and Microdot.

The second suite is useful for rough framework comparisons, but it is not a
production throughput benchmark. Each framework's test client has different
amounts of bookkeeping. Microdot's official test client is async, so the sync
adapter below keeps one event loop alive instead of creating a new loop for
each request.
"""

import asyncio
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from night import Night, Request


async def _empty_receive():
    return {"type": "http.request", "body": b"", "more_body": False}


def make_request(path: str) -> Request:
    return Request(
        scope={
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "server": ("bench", 80),
            "client": None,
        },
        receive=_empty_receive,
        send=None,
    )


class LegacyNight(Night):
    """Pre-fast-path dispatch behavior retained only for microbench comparison."""

    def _match_method(self, path: str, method: str):
        key = path.rstrip("/") or "/"
        candidates = self._static_route_index.get(key)
        if candidates is None:
            candidates = self._dynamic_route_index
        path_matched = False
        for route in candidates:
            match = route.pattern.match(path)
            if not match:
                continue
            path_matched = True
            if method in route.methods:
                return route, match.groupdict()
        if path_matched:
            from night import MethodNotAllowed
            raise MethodNotAllowed(self._allowed_methods_for_path(path))
        from night import NotFound
        raise NotFound()

    async def _call_endpoint(self, fn, req, params):
        import inspect
        import typing as t
        try:
            sig = inspect.signature(fn)
        except Exception:
            sig = None
        try:
            type_hints = t.get_type_hints(fn)
        except Exception:
            type_hints = {}
        kwargs = dict(params)
        if sig is not None:
            for name, param in sig.parameters.items():
                if name in kwargs and type_hints.get(name, param.annotation) is int:
                    try:
                        kwargs[name] = int(kwargs[name])
                    except Exception:
                        pass
        if sig is not None and "req" in sig.parameters:
            result = fn(req=req, **kwargs)
        elif sig is not None and sig.parameters:
            first = next(iter(sig.parameters.values()))
            if type_hints.get(first.name, first.annotation) is Request or first.name in ("request", "req"):
                result = fn(req, **kwargs)
            else:
                result = fn(**kwargs)
        else:
            result = fn(**kwargs)
        if inspect.isawaitable(result):
            result = await result
        return self._coerce_response(result)

    async def _call_route(self, route, req, params):
        return await self._call_endpoint(route.endpoint, req, params)


def _night_dynamic_handler(value: int):
    def handler(id: int):
        return {"route": value, "id": id}
    return handler


def build_night(app_type, *, many_dynamic: bool):
    app = app_type()

    for index in range(200):
        path = f"/static/{index}"

        def handler(index=index):
            return str(index)

        app.get(path)(handler)

    @app.get("/users/<int:id>")
    def user(id: int):
        return {"id": id}

    if many_dynamic:
        for index in range(200):
            app.get(f"/dynamic/{index}/<int:id>")(_night_dynamic_handler(index))

    return app


async def bench_night_hot_path(app, path: str, iterations: int) -> float:
    req = make_request(path)
    started = time.perf_counter_ns()
    for _ in range(iterations):
        route, params = app._match_method(path, "GET")
        await app._call_route(route, req, params)
    return (time.perf_counter_ns() - started) / iterations


def _bench_sync(call, iterations: int) -> float:
    started = time.perf_counter_ns()
    for _ in range(iterations):
        call()
    return (time.perf_counter_ns() - started) / iterations


def _flask_dynamic_handler(value: int):
    def handler(id: int):
        return {"route": value, "id": id}
    return handler


def build_flask(*, many_dynamic: bool):
    from flask import Flask

    app = Flask("night-bench")
    for index in range(200):
        app.add_url_rule(
            f"/static/{index}",
            f"static_{index}",
            lambda index=index: str(index),
        )

    @app.get("/users/<int:id>")
    def user(id: int):
        return {"id": id}

    if many_dynamic:
        for index in range(200):
            app.add_url_rule(
                f"/dynamic/{index}/<int:id>",
                f"dynamic_{index}",
                _flask_dynamic_handler(index),
            )

    return app, app.test_client()


def _robyn_static_handler(value: int):
    def handler(request):
        return str(value)
    return handler


def _robyn_dynamic_handler(value: int):
    def handler(request, id: int):
        return {"route": value, "id": id}
    return handler


def build_robyn(*, many_dynamic: bool):
    from robyn import Robyn
    from robyn.testing import TestClient

    app = Robyn(__file__)
    for index in range(200):
        app.get(f"/static/{index}")(_robyn_static_handler(index))

    def user(request, id: int):
        return {"id": id}
    app.get("/users/:id")(user)

    if many_dynamic:
        for index in range(200):
            app.get(f"/dynamic/{index}/:id")(_robyn_dynamic_handler(index))

    return app, TestClient(app)


def _bottle_dynamic_handler(value: int):
    def handler(id: int):
        return {"route": value, "id": id}
    return handler


def build_bottle(*, many_dynamic: bool):
    from bottle import Bottle
    from webtest import TestApp

    app = Bottle()
    for index in range(200):
        app.route(f"/static/{index}", method="GET", callback=lambda index=index: str(index))

    def user(id: int):
        return {"id": id}
    app.route("/users/<id:int>", method="GET", callback=user)

    if many_dynamic:
        for index in range(200):
            app.route(
                f"/dynamic/{index}/<id:int>",
                method="GET",
                callback=_bottle_dynamic_handler(index),
            )

    return app, TestApp(app)


def _fastapi_dynamic_handler(value: int):
    def handler(id: int):
        return {"route": value, "id": id}
    return handler


def build_fastapi(*, many_dynamic: bool):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    for index in range(200):
        def static_handler(index=index):
            return str(index)
        app.add_api_route(f"/static/{index}", static_handler, methods=["GET"])

    def user(id: int):
        return {"id": id}
    app.add_api_route("/users/{id}", user, methods=["GET"])

    if many_dynamic:
        for index in range(200):
            app.add_api_route(
                f"/dynamic/{index}/{{id}}",
                _fastapi_dynamic_handler(index),
                methods=["GET"],
            )

    return app, TestClient(app)


def _microdot_static_handler(value: int):
    async def handler(request):
        return str(value)
    return handler


def _microdot_dynamic_handler(value: int):
    async def handler(request, id: int):
        return {"route": value, "id": id}
    return handler


class _MicrodotSyncClient:
    def __init__(self, client):
        self.client = client
        self.loop = asyncio.new_event_loop()

    def get(self, path: str):
        return self.loop.run_until_complete(self.client.get(path))


def build_microdot(*, many_dynamic: bool):
    from microdot import Microdot
    from microdot.test_client import TestClient

    app = Microdot()
    for index in range(200):
        app.get(f"/static/{index}")(_microdot_static_handler(index))

    async def user(request, id: int):
        return {"id": id}
    app.get("/users/<int:id>")(user)

    if many_dynamic:
        for index in range(200):
            app.get(f"/dynamic/{index}/<int:id>")(_microdot_dynamic_handler(index))

    return app, _MicrodotSyncClient(TestClient(app))


def public_clients(*, many_dynamic: bool):
    night = build_night(Night, many_dynamic=many_dynamic).test_client()
    flask_app, flask = build_flask(many_dynamic=many_dynamic)
    robyn_app, robyn = build_robyn(many_dynamic=many_dynamic)
    bottle_app, bottle = build_bottle(many_dynamic=many_dynamic)
    fastapi_app, fastapi = build_fastapi(many_dynamic=many_dynamic)
    microdot_app, microdot = build_microdot(many_dynamic=many_dynamic)
    assert all(app is not None for app in (flask_app, robyn_app, bottle_app, fastapi_app, microdot_app))
    return {
        "Night": lambda path: night.get(path),
        "Flask": lambda path: flask.get(path),
        "Robyn": lambda path: robyn.get(path),
        "Bottle": lambda path: bottle.get(path),
        "FastAPI": lambda path: fastapi.get(path),
        "Microdot": lambda path: microdot.get(path),
    }


def bench_public_clients():
    print("\nIn-process public client benchmark")
    print("  (test clients do different bookkeeping; treat as rough comparison)")
    print("  (Microdot uses its official async client through one persistent event loop)")

    iterations = 300
    rounds = 3

    cases = (
        ("/static/199", False),
        ("/users/42", False),
        ("/dynamic/199/42", True),
    )
    cached = {}
    medians_by_case = {}
    for path, many_dynamic in cases:
        clients = cached.setdefault(many_dynamic, public_clients(many_dynamic=many_dynamic))
        print(f"\n{path}")
        medians = {}
        for name, request in clients.items():
            request(path)
            samples = [
                _bench_sync(lambda request=request, path=path: request(path), iterations)
                for _ in range(rounds)
            ]
            median = statistics.median(samples)
            medians[name] = median
            print(f"  {name:9s}: {median:10.1f} ns/op")
        medians_by_case[path] = medians

    base = medians_by_case["/users/42"]
    many = medians_by_case["/dynamic/199/42"]
    print("\nDynamic x200 scaling (/dynamic/199/42 vs /users/42)")
    for name in many:
        ratio = many[name] / base[name]
        delta = (ratio - 1.0) * 100.0
        print(f"  {name:9s}: {ratio:6.3f}x ({delta:+6.1f}%)")


async def main_hot_path():
    iterations = 5_000
    rounds = 5

    print("Night internal hot-path benchmark")
    cases = (
        ("/static/199", False),
        ("/users/42", False),
        ("/dynamic/199/42", True),
    )
    for path, many_dynamic in cases:
        print(f"\n{path}")
        results = {}
        for app_type in (LegacyNight, Night):
            app = build_night(app_type, many_dynamic=many_dynamic)
            samples = [await bench_night_hot_path(app, path, iterations) for _ in range(rounds)]
            median = statistics.median(samples)
            results[app_type.__name__] = median
            print(f"  {app_type.__name__:11s}: {median:9.1f} ns/op")

        baseline = results["LegacyNight"]
        fast = results["Night"]
        print(f"  speedup    : {baseline / fast:.2f}x")


if __name__ == "__main__":
    asyncio.run(main_hot_path())
    bench_public_clients()
