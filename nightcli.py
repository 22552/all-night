#!/usr/bin/env python3
"""NightCLI - project tooling for Night applications.

The CLI intentionally stays dependency-free.  It owns project scaffolding and
project discovery, while the Night runtime remains responsible for serving and
routing requests.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap
import tomllib
from typing import Any

CONFIG_NAME = "night.toml"
TEMPLATES = ("api", "site", "midnight", "cloudflare")

PROJECT_TOML = """[project]
name = {name!r}
template = {template!r}
app = {app!r}

[server]
host = "127.0.0.1"
port = 8000
"""

PYPROJECT_TOML = """[project]
name = {package!r}
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["all-night[standard]>=0.1.7"]

[tool.setuptools]
py-modules = ["app"]
"""

CLOUDFLARE_PYPROJECT_TOML = """[project]
name = {package!r}
version = "0.1.0"
requires-python = ">=3.13"
dependencies = ["all-night>=0.1.7", "workers-runtime-sdk"]

[dependency-groups]
dev = ["workers-py"]
"""

TEMPLATES_SOURCE = {
    "api": """from night import Night

app = Night().fast()

@app.get("/")
def index():
    return {"hello": "Night"}

@app.get("/health")
def health():
    return {"ok": True}
''',
    "site": """from night import Night, html

app = Night().fast()

@app.get("/")
def index():
    return html("""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Night</title></head>
<body><main><h1>Good evening.</h1><p>Your Night project is ready.</p></main></body>
</html>""")
''',
    "midnight": """from night import Night, html

app = Night().fast()

@app.get("/")
def index():
    return html("""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Midnight + Night</title></head>
<body><main><h1>Midnight project</h1><p>Install and configure all-night-midnight when adding live DOM behavior.</p></main></body>
</html>""")
''',
    "cloudflare": """from night import Night
from workers import WorkerEntrypoint

app = Night()

@app.get("/")
def index():
    return {"hello": "Night on Cloudflare Workers"}

class Default(WorkerEntrypoint):
    async def fetch(self, request):
        return await app.cloudflare_fetch(request)
''',
}


class CLIError(RuntimeError):
    """An expected command-line error."""


def project_root(start: Path | None = None) -> Path | None:
    """Find the nearest Night project, walking upward from start."""
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / CONFIG_NAME).is_file():
            return candidate
    return None


def read_config(root: Path) -> dict[str, Any]:
    try:
        with (root / CONFIG_NAME).open("rb") as file:
            config = tomllib.load(file)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise CLIError(f"Cannot read {root / CONFIG_NAME}: {exc}") from exc
    if not isinstance(config.get("project"), dict):
        raise CLIError(f"{root / CONFIG_NAME} needs a [project] section")
    return config


def require_project(directory: str | None) -> tuple[Path, dict[str, Any]]:
    root = Path(directory).resolve() if directory else project_root()
    if root is None:
        raise CLIError("No Night project found. Run 'nightcli new <name>' first or pass --project.")
    return root, read_config(root)


def app_target(config: dict[str, Any], explicit: str | None) -> str:
    target = explicit or config["project"].get("app", "app:app")
    if not isinstance(target, str) or ":" not in target:
        raise CLIError("App target must look like 'module:app'.")
    return target


def load_app(root: Path, target: str) -> Any:
    module_name, attribute = target.split(":", 1)
    if not module_name or not attribute:
        raise CLIError("App target must look like 'module:app'.")
    old_path = list(sys.path)
    old_cwd = Path.cwd()
    try:
        os.chdir(root)
        sys.path.insert(0, str(root))
        module = importlib.import_module(module_name)
        return getattr(module, attribute)
    except (ImportError, AttributeError) as exc:
        raise CLIError(f"Could not load {target}: {exc}") from exc
    finally:
        os.chdir(old_cwd)
        sys.path[:] = old_path


def command_new(args: argparse.Namespace) -> int:
    destination = Path(args.path or args.name).expanduser().resolve()
    if destination.exists():
        raise CLIError(f"{destination} already exists; refusing to overwrite it.")
    package = args.name.lower().replace("-", "_").replace(" ", "_")
    destination.mkdir(parents=True)
    app_file = "worker.py" if args.template == "cloudflare" else "app.py"
    target = f"{app_file[:-3]}:app"
    (destination / CONFIG_NAME).write_text(
        PROJECT_TOML.format(name=args.name, template=args.template, app=target), encoding="utf-8"
    )
    pyproject = CLOUDFLARE_PYPROJECT_TOML if args.template == "cloudflare" else PYPROJECT_TOML
    (destination / "pyproject.toml").write_text(pyproject.format(package=package), encoding="utf-8")
    (destination / app_file).write_text(TEMPLATES_SOURCE[args.template], encoding="utf-8")
    (destination / ".gitignore").write_text("__pycache__/\n.venv/\n.env\n", encoding="utf-8")
    print(f"Created Night project: {destination}")
    print(f"  template: {args.template}")
    print(f"  next: cd {destination.name} && nightcli run")
    return 0


def command_run(args: argparse.Namespace) -> int:
    root, config = require_project(args.project)
    target = app_target(config, args.app)
    server = config.get("server", {})
    host = args.host or server.get("host", "127.0.0.1")
    port = args.port or server.get("port", 8000)
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise CLIError("Port must be between 1 and 65535.")
    if importlib.util.find_spec("uvicorn") is None:
        raise CLIError("Uvicorn is required to run locally. Install 'all-night[standard]'.")
    command = [sys.executable, "-m", "uvicorn", target, "--host", host, "--port", str(port)]
    if args.reload:
        command.append("--reload")
    print(f"Night → http://{host}:{port} ({target})")
    return subprocess.run(command, cwd=root, check=False).returncode


def command_check(args: argparse.Namespace) -> int:
    root, config = require_project(args.project)
    target = app_target(config, args.app)
    app = load_app(root, target)
    routes = getattr(app, "routes", None)
    if routes is None:
        raise CLIError(f"{target} loaded, but does not look like a Night application (missing .routes).")
    print(f"OK  {target}")
    print(f"    {len(routes)} HTTP route(s), {len(getattr(app, 'websocket_routes', []))} WebSocket route(s)")
    return 0


def command_routes(args: argparse.Namespace) -> int:
    root, config = require_project(args.project)
    app = load_app(root, app_target(config, args.app))
    routes = getattr(app, "routes", None)
    if routes is None:
        raise CLIError("Target does not look like a Night application.")
    for route in routes:
        print(f"{','.join(sorted(route.methods)):20} {route.raw_path}")
    for route in getattr(app, "websocket_routes", []):
        print(f"WEBSOCKET             {route.raw_path}")
    return 0


def command_info(args: argparse.Namespace) -> int:
    root, config = require_project(args.project)
    project = config["project"]
    print(f"Night project: {project.get('name', root.name)}")
    print(f"Root:          {root}")
    print(f"Template:      {project.get('template', 'custom')}")
    print(f"App:           {project.get('app', 'app:app')}")
    server = config.get("server", {})
    if server:
        print(f"Local server:  http://{server.get('host', '127.0.0.1')}:{server.get('port', 8000)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nightcli",
        description="Create, inspect, validate, and run Night projects.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    new = sub.add_parser("new", help="Create a Night project")
    new.add_argument("name", help="Project name")
    new.add_argument("--template", choices=TEMPLATES, default="api")
    new.add_argument("--path", help="Destination directory (defaults to name)")
    new.set_defaults(handler=command_new)

    for name, handler, help_text in (
        ("run", command_run, "Run the local ASGI development server"),
        ("check", command_check, "Import and validate the configured Night app"),
        ("routes", command_routes, "Print application routes"),
        ("info", command_info, "Show project configuration"),
    ):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("--project", help="Project root; defaults to nearest night.toml")
        command.add_argument("--app", help="Override configured app target")
        if name == "run":
            command.add_argument("--host", help="Host to bind")
            command.add_argument("--port", type=int, help="Port to bind")
            command.add_argument("--reload", action="store_true", help="Reload when source files change")
        command.set_defaults(handler=handler)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except CLIError as exc:
        parser.error(str(exc))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
