#!/usr/bin/env python3
import asyncio
import cProfile
import gc
from pathlib import Path
import pstats
import statistics
import sys
import time
import urllib.parse

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.fast_path import build_night
from night import Night, TestResponse


def bench(fn, n=1000, rounds=5):
    vals=[]
    for _ in range(rounds):
        t0=time.perf_counter_ns()
        for _ in range(n): fn()
        vals.append((time.perf_counter_ns()-t0)/n)
    return statistics.median(vals)


class ReusedLoopClient:
    def __init__(self, app):
        self.app=app
        self.cookies={}
        self.loop=asyncio.new_event_loop()

    async def _request(self, method, path):
        sent=[]
        parsed=urllib.parse.urlsplit(path)
        hs=[]
        events=[{"type":"http.request","body":b"","more_body":False}]
        async def receive():
            return events.pop(0) if events else {"type":"http.disconnect"}
        async def send(event):
            sent.append(event)
        scope={"type":"http","method":method.upper(),"path":parsed.path or "/","query_string":parsed.query.encode(),"headers":hs}
        await self.app(scope, receive, send)
        start=next(e for e in sent if e["type"]=="http.response.start")
        chunks=[e.get("body",b"") for e in sent if e["type"]=="http.response.body"]
        return TestResponse(start["status"], {k.decode():v.decode() for k,v in start["headers"]}, b"".join(chunks))

    def get(self,path):
        return self.loop.run_until_complete(self._request("GET",path))


def run_case(path, many):
    app=build_night(Night,many_dynamic=many)
    normal=app.test_client()
    reused=ReusedLoopClient(app)
    normal.get(path); reused.get(path)

    gc.enable(); gc.collect()
    a=bench(lambda: normal.get(path))
    gc.disable()
    try:
        b=bench(lambda: normal.get(path))
    finally:
        gc.enable(); gc.collect()
    c=bench(lambda: reused.get(path))
    gc.disable()
    try:
        d=bench(lambda: reused.get(path))
    finally:
        gc.enable(); gc.collect()
    print(f"{path} many={many}")
    print(f"  asyncio.run + GC on : {a:10.1f} ns/op")
    print(f"  asyncio.run + GC off: {b:10.1f} ns/op  speedup={a/b:.3f}x")
    print(f"  reused loop + GC on : {c:10.1f} ns/op  speedup={a/c:.3f}x")
    print(f"  reused loop + GC off: {d:10.1f} ns/op  speedup={a/d:.3f}x")

    pr=cProfile.Profile(); pr.enable()
    for _ in range(1000): normal.get(path)
    pr.disable()
    print("  cProfile top cumulative:")
    pstats.Stats(pr).sort_stats("cumulative").print_stats(18)


def main():
    print("GC thresholds:", gc.get_threshold())
    run_case("/static/199", False)
    run_case("/users/42", False)
    run_case("/dynamic/199/42", True)

if __name__=="__main__":
    main()
