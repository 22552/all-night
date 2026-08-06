#!/usr/bin/env python3
"""Small routing/endpoint-dispatch microbenchmark for Night and FastNight.

Run with:
    python benchmarks/fast_path.py

This intentionally benchmarks framework hot paths without network or ASGI server
noise. It is for relative local measurements, not production throughput claims.
"""

from __future__ import annotations

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

def build(app_type):
    app = app_type()

    for index in range(200):
        path = f"/static/{index}"

        def handler(index=index):
            return str(index)

        app.get(path)(handler)

    @app.get("/users/<int:id>")
    def user(id: int):
        return {"id": id}

    return app


async def bench(app, path: str, iterations: int) -> float:
    req = make_request(path)
    started = time.perf_counter_ns()
    for _ in range(iterations):
        route, params = app._match_method(path, "GET")
        await app._call_endpoint(route.endpoint, req, params)
    return (time.perf_counter_ns() - started) / iterations


async def main():
    iterations = 20_000
    rounds = 7

    for path in ("/static/199", "/users/42"):
        print(f"\n{path}")
        results = {}
        for app_type in (LegacyNight, Night):
            app = build(app_type)
            samples = [await bench(app, path, iterations) for _ in range(rounds)]
            median = statistics.median(samples)
            results[app_type.__name__] = median
            print(f"  {app_type.__name__:9s}: {median:9.1f} ns/op")

        baseline = results["LegacyNight"]
        fast = results["Night"]
        print(f"  speedup  : {baseline / fast:.2f}x")


if __name__ == "__main__":
    asyncio.run(main())
