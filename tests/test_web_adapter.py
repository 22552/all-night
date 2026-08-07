import asyncio
import json

from night import Night
from night_web import handle_web


def run(coro):
    return asyncio.run(coro)


def test_web_adapter_get_query_and_headers():
    app = Night()

    @app.get("/hello/<int:user_id>")
    def hello(user_id: int, req):
        return {
            "id": user_id,
            "query": req.query.get("q"),
            "agent": req.header("user-agent"),
        }

    result = run(
        handle_web(
            app,
            method="GET",
            url="https://example.test/hello/42?q=night",
            headers=[("User-Agent", "night-web-test")],
        )
    )

    assert result.status == 200
    assert json.loads(result.body) == {
        "id": 42,
        "query": "night",
        "agent": "night-web-test",
    }


def test_web_adapter_post_body_and_response_headers():
    app = Night()

    @app.post("/echo")
    async def echo(req):
        return {"body": await req.text()}

    result = run(
        handle_web(
            app,
            method="POST",
            url="https://example.test/echo",
            headers={"content-type": "text/plain"},
            body=b"after dark",
        )
    )

    assert result.status == 200
    assert json.loads(result.body) == {"body": "after dark"}
    assert any(key.lower() == "content-type" for key, _ in result.headers)


def test_web_adapter_enforces_night_body_limit():
    app = Night(max_body_size=3)

    @app.post("/")
    async def index(req):
        return await req.text()

    result = run(
        handle_web(
            app,
            method="POST",
            url="https://example.test/",
            body=b"1234",
        )
    )

    assert result.status == 413
    assert result.body == b"Request body too large"
