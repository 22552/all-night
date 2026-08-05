import asyncio

from night import Night
from web_runtime import fetch


class DemoHeaders:
    def __init__(self, values=None):
        self.values = list(values or [])

    def entries(self):
        return iter(self.values)


class DemoArrayBuffer:
    def __init__(self, data: bytes):
        self.data = data

    def to_py(self):
        return self.data


class DemoRequest:
    def __init__(self, url: str, method: str = "GET", headers=None, body: bytes = b""):
        self.url = url
        self.method = method
        self.headers = DemoHeaders(headers)
        self._body = body

    async def arrayBuffer(self):
        return DemoArrayBuffer(self._body)


class DemoResponse:
    def __init__(self, body, init):
        self.body = bytes(body)
        self.status = init["status"]
        self.headers = init["headers"]

    @classmethod
    def new(cls, body, init):
        return cls(body, init)


app = Night()


@app.get("/hello")
def hello():
    return {"message": "Night on a Web-style runtime"}


@app.post("/echo")
async def echo(req):
    return {"echo": await req.json()}


async def main():
    hello_response = await fetch(
        app,
        DemoRequest("https://example.test/hello"),
        response_class=DemoResponse,
    )
    print(hello_response.status, hello_response.body.decode())

    echo_response = await fetch(
        app,
        DemoRequest(
            "https://example.test/echo",
            method="POST",
            headers=[("content-type", "application/json")],
            body=b'{"edge":true}',
        ),
        response_class=DemoResponse,
    )
    print(echo_response.status, echo_response.body.decode())


if __name__ == "__main__":
    asyncio.run(main())
