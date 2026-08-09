from __future__ import annotations

import contextlib
import io
from pathlib import Path
import tempfile
import unittest

from nightcli import main


class NightCLITests(unittest.TestCase):
    def run_cli(self, *argv: str) -> tuple[int, str]:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(list(argv))
        return code, output.getvalue()

    def test_api_project_can_be_created_checked_and_inspected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "demo"
            code, output = self.run_cli("new", "demo", "--template", "api", "--path", str(root))
            self.assertEqual(code, 0)
            self.assertIn("Created Night project", output)
            self.assertTrue((root / "night.toml").is_file())

            code, output = self.run_cli("check", "--project", str(root))
            self.assertEqual(code, 0)
            self.assertIn("2 HTTP route(s)", output)

            code, output = self.run_cli("routes", "--project", str(root))
            self.assertEqual(code, 0)
            self.assertIn("GET                  /health", output)

            code, output = self.run_cli("routes", "--project", str(root), "--format", "json")
            self.assertEqual(code, 0)
            self.assertIn('"path": "/health"', output)

            code, output = self.run_cli("openapi", "--project", str(root))
            self.assertEqual(code, 0)
            self.assertIn("Wrote OpenAPI document", output)
            self.assertIn('"openapi"', (root / "openapi.json").read_text(encoding="utf-8"))

            code, output = self.run_cli("info", "--project", str(root))
            self.assertEqual(code, 0)
            self.assertIn("Template:      api", output)

    def test_project_lookup_walks_up_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "demo"
            self.run_cli("new", "demo", "--path", str(root))
            nested = root / "src" / "feature"
            nested.mkdir(parents=True)

            from nightcli import project_root

            self.assertEqual(project_root(nested), root)


    def test_existing_project_can_be_initialized(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "existing"
            root.mkdir()
            (root / "app.py").write_text("from night import Night\napp = Night()\n", encoding="utf-8")

            code, output = self.run_cli("init", "--path", str(root), "--app", "app:app")
            self.assertEqual(code, 0)
            self.assertIn("Initialized Night project", output)

            code, output = self.run_cli("check", "--project", str(root))
            self.assertEqual(code, 0)
            self.assertIn("0 HTTP route(s)", output)


if __name__ == "__main__":
    unittest.main()
