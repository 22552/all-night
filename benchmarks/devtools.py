from __future__ import annotations

import statistics
import time

from night import Night, TestClient
from night_devtools import enable_devtools

REQUESTS = 12000
ROUNDS = 7
WARMUP = 1000


def build(enabled: bool) -> TestClient:
    app = Night(debug=True)

    @app.get("/")
    def index():
        return {"ok": True}

    if enabled:
        enable_devtools(app, request_history=100)
    return TestClient(app)


def measure(client: TestClient, count: int) -> float:
    start = time.perf_counter()
    for _ in range(count):
        response = client.get("/")
        if response.status_code != 200:
            raise RuntimeError(response.status_code)
    return count / (time.perf_counter() - start)


def main() -> None:
    off = build(False)
    on = build(True)
    measure(off, WARMUP)
    measure(on, WARMUP)

    off_runs: list[float] = []
    on_runs: list[float] = []
    for round_index in range(ROUNDS):
        order = (("off", off), ("on", on)) if round_index % 2 == 0 else (("on", on), ("off", off))
        for name, client in order:
            value = measure(client, REQUESTS)
            (off_runs if name == "off" else on_runs).append(value)

    off_median = statistics.median(off_runs)
    on_median = statistics.median(on_runs)
    throughput_drop = (1.0 - on_median / off_median) * 100.0
    added_us = (1.0 / on_median - 1.0 / off_median) * 1_000_000.0

    print("Night DevTools TestClient benchmark")
    print(f"requests/round: {REQUESTS:,}; rounds: {ROUNDS}")
    print(f"OFF median: {off_median:,.1f} req/s")
    print(f"ON  median: {on_median:,.1f} req/s")
    print(f"throughput drop: {throughput_drop:.2f}%")
    print(f"estimated added cost: {added_us:.2f} us/request")
    print("OFF runs:", ", ".join(f"{x:,.0f}" for x in off_runs))
    print("ON runs: ", ", ".join(f"{x:,.0f}" for x in on_runs))


if __name__ == "__main__":
    main()
