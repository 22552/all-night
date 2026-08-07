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


def test_web_adapter_normalizes_cloudflare_client_ip():
    app = Night()

    @app.get("/")
    def index(req):
        return {"ip": req.client[0], "ua": req.header("user-agent")}

    result = run(
        handle_web(
            app,
            method="GET",
            url="https://example.test/",
            headers=[
                ("CF-Connecting-IP", "203.0.113.10"),
                ("User-Agent", "cloudflare-test"),
            ],
        )
    )

    assert json.loads(result.body) == {
        "ip": "203.0.113.10",
        "ua": "cloudflare-test",
    }


def test_web_adapter_normalizes_netlify_client_ip():
    app = Night()

    @app.get("/")
    def index(req):
        return {"ip": req.client[0], "ua": req.header("user-agent")}

    result = run(
        handle_web(
            app,
            method="GET",
            url="https://example.test/",
            headers=[
                ("X-Nf-Client-Connection-Ip", "198.51.100.7"),
                ("User-Agent", "netlify-test"),
            ],
        )
    )

    assert json.loads(result.body) == {
        "ip": "198.51.100.7",
        "ua": "netlify-test",
    }


def test_web_adapter_does_not_trust_generic_forwarded_for():
    app = Night()

    @app.get("/")
    def index(req):
        return {"client": req.client}

    result = run(
        handle_web(
            app,
            method="GET",
            url="https://example.test/",
            headers=[("X-Forwarded-For", "192.0.2.55")],
        )
    )

    assert json.loads(result.body) == {"client": None}


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
