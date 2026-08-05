import asyncio

from night import Night, Request
from portable_runtime import handle


def make_request(method="GET", path="/"):
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "query_string": b"",
        "headers": [],
        "scheme": "https",
        "server": ("test", 443),
        "client": ("127.0.0.1", 12345),
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        pass

    return Request(scope=scope, receive=receive, send=send)


def test_portable_get():
    app = Night()

    @app.get("/")
    def index():
        return {"ok": True}

    response = asyncio.run(handle(app, make_request()))
    assert response.status == 200
    assert response.body == b'{"ok":true}'


def test_portable_head():
    app = Night()

    @app.get("/")
    def index():
        return "hello"

    response = asyncio.run(handle(app, make_request("HEAD")))
    assert response.status == 200
    assert response.body == b""


def test_portable_options():
    app = Night()

    @app.get("/")
    def index():
        return "hello"

    response = asyncio.run(handle(app, make_request("OPTIONS")))
    assert response.status == 204
    assert "GET" in response.headers["allow"]
    assert "HEAD" in response.headers["allow"]
    assert "OPTIONS" in response.headers["allow"]
