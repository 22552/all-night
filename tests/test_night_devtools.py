from __future__ import annotations

import asyncio
import unittest

from night import Night, TestClient as NightTestClient
from night_devtools import enable_devtools


class DevToolsTests(unittest.TestCase):
    def test_debug_blueprint_serves_dashboard_and_route_data(self):
        app = Night(debug=True)

        @app.get("/hello")
        def hello():
            return {"hello": "night"}

        @app.get("/users/<int:user_id>")
        def user(user_id: int):
            return {"id": user_id}

        blueprint = enable_devtools(app)
        self.assertEqual(blueprint.name, "night_devtools")

        client = NightTestClient(app)
        page = client.get("/__night__")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Night DevTools", page.text)
        self.assertIn("Recent requests", page.text)
        self.assertIn("WebSockets", page.text)
        self.assertIn("SSE push", page.text)
        self.assertIn("EventSource", page.text)
        self.assertEqual(client.get("/__night__/").status_code, 200)

        routes = client.get("/__night__/api/routes").get_json()
        self.assertTrue(any(item["path"] == "/hello" for item in routes["routes"]))
        dynamic = next(item for item in routes["routes"] if item["path"] == "/users/<int:user_id>")
        self.assertTrue(dynamic["dynamic"])
        self.assertEqual(dynamic["params"], ["user_id"])

        summary = client.get("/__night__/api/summary").get_json()
        self.assertTrue(summary["debug"])
        self.assertGreaterEqual(summary["routes"], 7)
        self.assertEqual(summary["middlewares"], 0)
        self.assertIn("fast", summary)
        self.assertEqual(summary["websocket_active"], 0)

    def test_events_endpoint_streams_sse_snapshot(self):
        app = Night(debug=True)
        blueprint = enable_devtools(app)
        endpoint = next(route.endpoint for route in blueprint.routes if route.raw_path == "/events")

        async def collect_first_chunk():
            response = await endpoint()
            sent = []
            first_chunk = asyncio.Event()

            async def receive():
                await asyncio.Event().wait()

            async def send(event):
                sent.append(event)
                if event["type"] == "http.response.body" and event.get("body"):
                    first_chunk.set()

            task = asyncio.create_task(
                response(
                    {"type": "http", "method": "GET", "path": "/__night__/events", "headers": []},
                    receive,
                    send,
                )
            )
            await asyncio.wait_for(first_chunk.wait(), timeout=0.5)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            return sent

        sent = asyncio.run(collect_first_chunk())
        start = next(event for event in sent if event["type"] == "http.response.start")
        headers = {key.decode(): value.decode() for key, value in start["headers"]}
        body = b"".join(event.get("body", b"") for event in sent if event["type"] == "http.response.body")
        self.assertEqual(headers["content-type"], "text/event-stream")
        self.assertEqual(headers["cache-control"], "no-cache")
        self.assertIn(b'data: {"type":"snapshot"', body)
        self.assertEqual(app._night_devtools_live_queues, set())

    def test_request_history_records_status_latency_and_errors(self):
        app = Night(debug=True)

        @app.get("/hello")
        def hello():
            return "hello"

        enable_devtools(app)
        client = NightTestClient(app)

        self.assertEqual(client.get("/hello").status_code, 200)
        self.assertEqual(client.get("/missing").status_code, 404)

        history = client.get("/__night__/api/requests").get_json()["requests"]
        self.assertEqual([item["path"] for item in history[:2]], ["/missing", "/hello"])
        self.assertEqual(history[0]["status"], 404)
        self.assertEqual(history[1]["status"], 200)
        self.assertGreaterEqual(history[0]["duration_ms"], 0)
        self.assertIsNotNone(history[0]["error"])
        self.assertIsNone(history[1]["error"])
        self.assertFalse(any(item["path"].startswith("/__night__") for item in history))

    def test_request_detail_redacts_credentials_and_keeps_traceback(self):
        app = Night(debug=True)

        @app.get("/boom")
        def boom():
            raise RuntimeError("kaboom")

        enable_devtools(app)
        client = NightTestClient(app)
        response = client.get(
            "/boom?mode=test",
            headers={"authorization": "Bearer secret", "x-api-key": "abc", "x-visible": "yes"},
        )
        self.assertEqual(response.status_code, 500)

        compact = client.get("/__night__/api/requests").get_json()["requests"][0]
        self.assertNotIn("traceback", compact["error"])

        detail = client.get(f"/__night__/api/requests/{compact['id']}").get_json()
        self.assertEqual(detail["query"]["mode"], "test")
        self.assertEqual(detail["headers"]["authorization"], "[redacted]")
        self.assertEqual(detail["headers"]["x-api-key"], "[redacted]")
        self.assertEqual(detail["headers"]["x-visible"], "yes")
        self.assertEqual(detail["error"]["type"], "RuntimeError")
        self.assertIn("kaboom", detail["error"]["traceback"])

    def test_request_detail_returns_404_when_trace_expired(self):
        app = Night(debug=True)
        enable_devtools(app, request_history=1)
        client = NightTestClient(app)
        self.assertEqual(client.get("/__night__/api/requests/999").status_code, 404)

    def test_request_history_is_bounded(self):
        app = Night(debug=True)

        @app.get("/<int:value>")
        def value(value: int):
            return {"value": value}

        enable_devtools(app, request_history=2)
        client = NightTestClient(app)
        client.get("/1")
        client.get("/2")
        client.get("/3")

        history = client.get("/__night__/api/requests").get_json()["requests"]
        self.assertEqual(len(history), 2)
        self.assertEqual([item["path"] for item in history], ["/3", "/2"])

    def test_existing_user_middleware_is_preserved(self):
        app = Night(debug=True)
        calls = []

        async def middleware(req, call_next):
            calls.append(req.path)
            return await call_next()

        app.use(middleware)

        @app.get("/hello")
        def hello():
            return "hello"

        enable_devtools(app)
        client = NightTestClient(app)
        self.assertEqual(client.get("/hello").status_code, 200)
        self.assertEqual(calls, ["/hello"])
        self.assertEqual(client.get("/__night__/api/summary").get_json()["middlewares"], 1)

    def test_websocket_transport_trace_records_closed_connection(self):
        app = Night(debug=True)
        enable_devtools(app)

        sent = []

        async def receive():
            return {"type": "websocket.disconnect", "code": 1000}

        async def send(event):
            sent.append(event)

        scope = {
            "type": "websocket",
            "path": "/no-websocket-route",
            "client": ("127.0.0.1", 4321),
        }
        asyncio.run(app._handle_websocket(scope, receive, send))

        self.assertEqual(app._night_devtools_ws_active, {})
        self.assertEqual(len(app._night_devtools_ws_recent), 1)
        trace = app._night_devtools_ws_recent[-1]
        self.assertEqual(trace["path"], "/no-websocket-route")
        self.assertEqual(trace["client"], "127.0.0.1:4321")
        self.assertEqual(trace["close_code"], 1008)
        self.assertGreaterEqual(trace["duration_ms"], 0)

        client = NightTestClient(app)
        payload = client.get("/__night__/api/websockets").get_json()
        self.assertEqual(payload["active"], [])
        self.assertEqual(payload["recent"][0]["path"], "/no-websocket-route")

    def test_devtools_refuses_non_debug_application(self):
        with self.assertRaisesRegex(RuntimeError, "debug=True"):
            enable_devtools(Night())

    def test_devtools_validates_history_sizes(self):
        with self.assertRaisesRegex(ValueError, "request_history"):
            enable_devtools(Night(debug=True), request_history=0)
        with self.assertRaisesRegex(ValueError, "websocket_history"):
            enable_devtools(Night(debug=True), websocket_history=0)


if __name__ == "__main__":
    unittest.main()
