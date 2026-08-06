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
from night_fast import FastNight


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
        for app_type in (Night, FastNight):
            app = build(app_type)
            samples = [await bench(app, path, iterations) for _ in range(rounds)]
            median = statistics.median(samples)
            results[app_type.__name__] = median
            print(f"  {app_type.__name__:9s}: {median:9.1f} ns/op")

        baseline = results["Night"]
        fast = results["FastNight"]
        print(f"  speedup  : {baseline / fast:.2f}x")


if __name__ == "__main__":
    asyncio.run(main())
