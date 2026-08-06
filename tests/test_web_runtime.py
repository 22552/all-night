import asyncio

from night import Night
from web_runtime import fetch


class FakeHeaders:
    def __init__(self, values=None):
        self.values = list(values or [])

    def entries(self):
        return iter(self.values)


class FakeArrayBuffer:
    def __init__(self, data: bytes):
        self.data = data

    def to_py(self):
        return self.data


class FakeRequest:
    def __init__(self, url: str, method: str = "GET", headers=None, body: bytes = b""):
        self.url = url
        self.method = method
        self.headers = FakeHeaders(headers)
        self._body = body

    async def arrayBuffer(self):
        return FakeArrayBuffer(self._body)


class FakeWebResponse:
    def __init__(self, body, init):
        self.body = bytes(body)
        self.status = init["status"]
        self.headers = init["headers"]

    @classmethod
    def new(cls, body, init):
        return cls(body, init)


def test_web_get_adapter():
    app = Night()

    @app.get("/hello")
    def hello():
        return {"hello": "edge"}

    request = FakeRequest("https://example.test/hello?x=1")
    response = asyncio.run(fetch(app, request, response_class=FakeWebResponse))

    assert response.status == 200
    assert response.body == b'{"hello":"edge"}'


def test_web_post_body_adapter():
    app = Night()

    @app.post("/echo")
    async def echo(req):
        return await req.json()

    request = FakeRequest(
        "https://example.test/echo",
        method="POST",
        headers=[("content-type", "application/json")],
        body=b'{"night":"edge"}',
    )
    response = asyncio.run(fetch(app, request, response_class=FakeWebResponse))

    assert response.status == 200
    assert response.body == b'{"night":"edge"}'


def test_web_head_adapter():
    app = Night()

    @app.get("/hello")
    def hello():
        return "hello"

    request = FakeRequest("https://example.test/hello", method="HEAD")
    response = asyncio.run(fetch(app, request, response_class=FakeWebResponse))

    assert response.status == 200
    assert response.body == b""
