import asyncio
from pathlib import Path

from night import Night


def request(app, path):
    events = []
    scope = {"type": "http", "http_version": "1.1", "method": "GET", "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": b"", "headers": []}
    async def receive(): return {"type": "http.request", "body": b"", "more_body": False}
    async def send(event): events.append(event)
    asyncio.run(app(scope, receive, send))
    return events


def test_app_send_file_publishes_route(tmp_path: Path):
    source = tmp_path / "test.png"
    source.write_bytes(b"PNGDATA")
    app = Night()
    app.send_file(str(source), "test")
    events = request(app, "/test")
    assert events[0]["status"] == 200
    assert events[-1]["body"] == b"PNGDATA"


def test_app_send_file_accepts_leading_slash(tmp_path: Path):
    source = tmp_path / "x.txt"
    source.write_text("hello")
    app = Night()
    app.send_file(str(source), "/hello")
    events = request(app, "/hello")
    assert events[-1]["body"] == b"hello"
