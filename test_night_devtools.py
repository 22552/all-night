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

        blueprint = enable_devtools(app)
        self.assertEqual(blueprint.name, "night_devtools")

        client = TestClient(app)
        page = client.get("/__night__")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Night DevTools", page.text)
        self.assertEqual(client.get("/__night__/").status_code, 200)

        routes = client.get("/__night__/api/routes").get_json()
        self.assertTrue(any(item["path"] == "/hello" for item in routes["routes"]))

        summary = client.get("/__night__/api/summary").get_json()
        self.assertTrue(summary["debug"])
        self.assertGreaterEqual(summary["routes"], 4)

    def test_devtools_refuses_non_debug_application(self):
        with self.assertRaisesRegex(RuntimeError, "debug=True"):
            enable_devtools(Night())


if __name__ == "__main__":
    unittest.main()
