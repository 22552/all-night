#!/usr/bin/env python3
"""Deployment-oriented command line interface for Night projects.

This file intentionally uses only Python's standard library. Existing framework
commands are delegated to ``night.cli``; cloud deployment adapters invoke the
provider's official CLI or a configured HTTPS deploy hook.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import urllib.error
import urllib.request


def _run(command: list[str], *, cwd: Path, dry_run: bool = False) -> int:
    print("$ " + shlex.join(command))
    if dry_run:
        return 0
    try:
        completed = subprocess.run(command, cwd=cwd, check=False)
    except OSError as exc:
        print(f"night deploy: failed to start {command[0]}: {exc}", file=sys.stderr)
        return 127
    return completed.returncode


def _require_command(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise RuntimeError(f"required command not found: {name}")
    return path


def _post_deploy_hook(url: str, *, dry_run: bool = False) -> int:
    if not url.startswith("https://"):
        raise RuntimeError("deploy hooks must use HTTPS")
    print("POST <deploy-hook>")
    if dry_run:
        return 0
    request = urllib.request.Request(
        url,
        data=b"{}",
        headers={"content-type": "application/json", "user-agent": "night-cli/1"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8", errors="replace")
            print(f"deploy accepted: HTTP {response.status}")
            if body:
                try:
                    print(json.dumps(json.loads(body), ensure_ascii=False, indent=2))
                except json.JSONDecodeError:
                    print(body)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"night deploy: hook returned HTTP {exc.code}: {detail}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"night deploy: hook request failed: {exc.reason}", file=sys.stderr)
        return 1
    return 0


def _deploy(args: argparse.Namespace) -> int:
    project = Path(args.project).expanduser().resolve()
    if not project.is_dir():
        print(f"night deploy: project directory does not exist: {project}", file=sys.stderr)
        return 2

    provider = args.provider
    try:
        if provider == "render":
            hook = args.hook or os.environ.get("RENDER_DEPLOY_HOOK") or os.environ.get("NIGHT_DEPLOY_HOOK")
            if not hook:
                raise RuntimeError(
                    "set RENDER_DEPLOY_HOOK (or NIGHT_DEPLOY_HOOK), or pass --hook"
                )
            return _post_deploy_hook(hook, dry_run=args.dry_run)

        if provider == "railway":
            executable = _require_command("railway")
            command = [executable, "up"]
            if args.detach:
                command.append("--detach")
            return _run(command, cwd=project, dry_run=args.dry_run)

        if provider == "fly":
            executable = shutil.which("flyctl") or shutil.which("fly")
            if executable is None:
                raise RuntimeError("required command not found: flyctl")
            command = [executable, "deploy"]
            if args.remote_only:
                command.append("--remote-only")
            return _run(command, cwd=project, dry_run=args.dry_run)

        if provider == "docker":
            executable = _require_command("docker")
            image = args.image or project.name.lower().replace("_", "-")
            command = [executable, "build", "-t", image]
            if args.platform:
                command.extend(["--platform", args.platform])
            command.append(".")
            return _run(command, cwd=project, dry_run=args.dry_run)

        raise RuntimeError(f"unsupported provider: {provider}")
    except RuntimeError as exc:
        print(f"night deploy: {exc}", file=sys.stderr)
        return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="night")
    sub = parser.add_subparsers(dest="command")

    deploy = sub.add_parser("deploy", help="deploy the current Night project")
    deploy.add_argument(
        "--provider",
        choices=("render", "railway", "fly", "docker"),
        default="render",
        help="deployment backend (default: render)",
    )
    deploy.add_argument("--project", default=".", help="project directory")
    deploy.add_argument("--dry-run", action="store_true", help="print actions without executing them")
    deploy.add_argument("--hook", help="HTTPS deploy hook; avoids storing it in project files")
    deploy.add_argument("--detach", action="store_true", help="pass --detach to Railway")
    deploy.add_argument("--remote-only", action="store_true", help="pass --remote-only to Fly")
    deploy.add_argument("--image", help="Docker image tag")
    deploy.add_argument("--platform", help="Docker target platform, e.g. linux/amd64")

    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "deploy":
        parser = _build_parser()
        args = parser.parse_args(argv)
        return _deploy(args)

    # Keep all existing commands (run, routes, shell) working through one CLI.
    try:
        from night import cli as framework_cli
    except ImportError as exc:
        print(f"night: cannot import framework CLI: {exc}", file=sys.stderr)
        return 1
    return framework_cli(argv)


if __name__ == "__main__":
    raise SystemExit(main())
