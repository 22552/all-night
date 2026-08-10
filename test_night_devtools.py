from __future__ import annotations

import unittest

from night import Night, TestClient
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

        client = TestClient(app)
        page = client.get("/__night__")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Night DevTools", page.text)
        self.assertIn("Recent requests", page.text)
        self.assertEqual(client.get("/__night__/").status_code, 200)

        routes = client.get("/__night__/api/routes").get_json()
        self.assertTrue(any(item["path"] == "/hello" for item in routes["routes"]))
        dynamic = next(item for item in routes["routes"] if item["path"] == "/users/<int:user_id>")
        self.assertTrue(dynamic["dynamic"])
        self.assertEqual(dynamic["params"], ["user_id"])

        summary = client.get("/__night__/api/summary").get_json()
        self.assertTrue(summary["debug"])
        self.assertGreaterEqual(summary["routes"], 5)
        self.assertGreaterEqual(summary["middlewares"], 1)
        self.assertIn("fast", summary)

    def test_request_history_records_status_latency_and_errors(self):
        app = Night(debug=True)

        @app.get("/hello")
        def hello():
            return "hello"

        enable_devtools(app)
        client = TestClient(app)

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

    def test_request_history_is_bounded(self):
        app = Night(debug=True)

        @app.get("/<int:value>")
        def value(value: int):
            return {"value": value}

        enable_devtools(app, request_history=2)
        client = TestClient(app)
        client.get("/1")
        client.get("/2")
        client.get("/3")

        history = client.get("/__night__/api/requests").get_json()["requests"]
        self.assertEqual(len(history), 2)
        self.assertEqual([item["path"] for item in history], ["/3", "/2"])

    def test_devtools_refuses_non_debug_application(self):
        with self.assertRaisesRegex(RuntimeError, "debug=True"):
            enable_devtools(Night())

    def test_devtools_validates_history_size(self):
        with self.assertRaisesRegex(ValueError, "request_history"):
            enable_devtools(Night(debug=True), request_history=0)


if __name__ == "__main__":
    unittest.main()
