from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, got {count}")
    return text.replace(old, new, 1)


night_path = ROOT / "night.py"
night = night_path.read_text()

marker = '''class Night(Router):\n'''
plan_code = '''CALL_KWARGS = 0\nCALL_REQUEST_POSITIONAL = 1\nCALL_REQUEST_KEYWORD = 2\n\n\n@dataclasses.dataclass(frozen=True, slots=True)\nclass _EndpointPlan:\n    signature: inspect.Signature | None\n    type_hints: dict[str, t.Any]\n    call_mode: int\n    int_params: tuple[str, ...]\n    body_model: type | None\n    body_candidates: tuple[str, ...]\n\n\ndef _compile_endpoint(fn: t.Callable) -> _EndpointPlan:\n    try:\n        signature = inspect.signature(fn)\n    except (TypeError, ValueError):\n        signature = None\n\n    try:\n        type_hints = t.get_type_hints(fn)\n    except Exception:\n        type_hints = {}\n\n    call_mode = CALL_KWARGS\n    int_params: list[str] = []\n    body_candidates: list[str] = []\n\n    if signature is not None:\n        params = tuple(signature.parameters.values())\n        if "req" in signature.parameters:\n            call_mode = CALL_REQUEST_KEYWORD\n        elif params:\n            first = params[0]\n            first_type = type_hints.get(first.name, first.annotation)\n            if first_type is Request or first.name in {"request", "req"}:\n                call_mode = CALL_REQUEST_POSITIONAL\n\n        for param in params:\n            annotation = type_hints.get(param.name, param.annotation)\n            if annotation is int:\n                int_params.append(param.name)\n            if param.name not in {"req", "request"}:\n                body_candidates.append(param.name)\n\n    return _EndpointPlan(\n        signature=signature,\n        type_hints=type_hints,\n        call_mode=call_mode,\n        int_params=tuple(int_params),\n        body_model=getattr(fn, "__night_body_model__", None),\n        body_candidates=tuple(body_candidates),\n    )\n\n\nclass Night(Router):\n'''
night = replace_once(night, marker, plan_code, "endpoint plan insertion")

old_init = '''        self._static_route_index: dict[str, list[Route]] = {}\n        self._dynamic_route_index: list[Route] = []\n'''
new_init = '''        self._static_route_index: dict[str, list[Route]] = {}\n        self._dynamic_route_index: list[Route] = []\n        self._static_method_index: dict[str, dict[str, Route]] = {}\n        self._static_methods_by_path: dict[str, set[str]] = {}\n        self._endpoint_plans: dict[t.Callable, _EndpointPlan] = {}\n'''
night = replace_once(night, old_init, new_init, "Night indexes")

old_added = '''    def _on_route_added(self, route: Route):\n        key = route.raw_path.rstrip("/") or "/"\n        if "<" in route.raw_path:\n            self._dynamic_route_index.append(route)\n        else:\n            self._static_route_index.setdefault(key, []).append(route)\n'''
new_added = '''    def _on_route_added(self, route: Route):\n        key = route.raw_path.rstrip("/") or "/"\n        self._endpoint_plans[route.endpoint] = _compile_endpoint(route.endpoint)\n        if "<" in route.raw_path:\n            self._dynamic_route_index.append(route)\n            return\n\n        self._static_route_index.setdefault(key, []).append(route)\n        methods = self._static_methods_by_path.setdefault(key, set())\n        for method in route.methods:\n            methods.add(method)\n            self._static_method_index.setdefault(method, {})[key] = route\n'''
night = replace_once(night, old_added, new_added, "route registration fast path")

old_mount = '''        self._static_route_index.clear()\n        self._dynamic_route_index.clear()\n        for route in self.routes: self._on_route_added(route)\n'''
new_mount = '''        self._static_route_index.clear()\n        self._dynamic_route_index.clear()\n        self._static_method_index.clear()\n        self._static_methods_by_path.clear()\n        self._endpoint_plans.clear()\n        for route in self.routes: self._on_route_added(route)\n'''
night = replace_once(night, old_mount, new_mount, "mount index rebuild")

old_match = '''    def _match_method(self, path: str, method: str) -> tuple[Route, dict[str, str]]:\n        key = path.rstrip("/") or "/"\n        candidates = self._static_route_index.get(key)\n        if candidates is None:\n            candidates = self._dynamic_route_index\n        path_matched = False\n        for route in candidates:\n            match = route.pattern.match(path)\n            if not match:\n                continue\n            path_matched = True\n            if method in route.methods:\n                return route, match.groupdict()\n        if path_matched:\n            raise MethodNotAllowed(self._allowed_methods_for_path(path))\n        raise NotFound()\n'''
new_match = '''    def _match_method(self, path: str, method: str) -> tuple[Route, dict[str, str]]:\n        key = path.rstrip("/") or "/"\n\n        # Hono-style hot path: exact static routes are two hash lookups and\n        # avoid regex matching entirely. Dynamic routes use the proven matcher.\n        route = self._static_method_index.get(method, {}).get(key)\n        if route is not None:\n            return route, {}\n\n        if key in self._static_methods_by_path:\n            raise MethodNotAllowed(self._allowed_methods_for_path(path))\n\n        path_matched = False\n        for route in self._dynamic_route_index:\n            match = route.pattern.match(path)\n            if not match:\n                continue\n            path_matched = True\n            if method in route.methods:\n                return route, match.groupdict()\n        if path_matched:\n            raise MethodNotAllowed(self._allowed_methods_for_path(path))\n        raise NotFound()\n'''
night = replace_once(night, old_match, new_match, "method matcher")

start = night.index('    async def _call_endpoint(self, fn: t.Callable, req: Request, params: dict[str, str]) -> Response:\n')
end = night.index('    async def _run_before_hooks', start)
new_call = '''    async def _call_endpoint(self, fn: t.Callable, req: Request, params: dict[str, str]) -> Response:\n        plan = self._endpoint_plans.get(fn)\n        if plan is None:\n            plan = _compile_endpoint(fn)\n            self._endpoint_plans[fn] = plan\n\n        kwargs: dict[str, t.Any] = dict(params)\n\n        if plan.body_model is not None:\n            payload = await req.json()\n            validated = _validate_dataclass(plan.body_model, payload)\n            target = next((name for name in plan.body_candidates if name not in kwargs), None)\n            if target is not None:\n                kwargs[target] = validated\n            else:\n                kwargs.setdefault("data", validated)\n\n        for name in plan.int_params:\n            if name in kwargs and not isinstance(kwargs[name], int):\n                try:\n                    kwargs[name] = int(kwargs[name])\n                except (TypeError, ValueError):\n                    pass\n\n        if plan.call_mode == CALL_REQUEST_KEYWORD:\n            result = fn(req=req, **kwargs)\n        elif plan.call_mode == CALL_REQUEST_POSITIONAL:\n            result = fn(req, **kwargs)\n        else:\n            result = fn(**kwargs)\n\n        if inspect.isawaitable(result):\n            result = await t.cast(t.Awaitable, result)\n        return self._coerce_response(result)\n\n'''
night = night[:start] + new_call + night[end:]

old_allowed = '''    def _allowed_methods_for_path(self, path: str) -> set[str]:\n        methods: set[str] = set()\n        for r in self.routes:\n            if r.pattern.match(path):\n                methods |= set(r.methods)\n        if "GET" in methods:\n            methods.add("HEAD")\n        return methods\n'''
new_allowed = '''    def _allowed_methods_for_path(self, path: str) -> set[str]:\n        key = path.rstrip("/") or "/"\n        static_methods = self._static_methods_by_path.get(key)\n        if static_methods is not None:\n            methods = set(static_methods)\n        else:\n            methods: set[str] = set()\n            for route in self._dynamic_route_index:\n                if route.pattern.match(path):\n                    methods |= set(route.methods)\n        if "GET" in methods:\n            methods.add("HEAD")\n        return methods\n'''
night = replace_once(night, old_allowed, new_allowed, "allowed methods fast path")

night_path.write_text(night)

# Cloudflare template now imports Night directly; the optimization is part of Night.
entry_path = ROOT / "deploy/cloudflare-night/src/entry.py"
entry = entry_path.read_text()
entry = entry.replace("from night import HTMLResponse\nfrom night_fast import FastNight\n", "from night import HTMLResponse, Night\n")
entry = entry.replace("app = FastNight()", "app = Night()")
entry_path.write_text(entry)

package_path = ROOT / "deploy/cloudflare-night/package.json"
package = package_path.read_text()
package = package.replace(" && cp night_fast.py src/night_fast.py", "")
package_path.write_text(package)

workflow_path = ROOT / ".github/workflows/test.yml"
workflow = workflow_path.read_text()
workflow = workflow.replace("src/night.py src/night_fast.py src/portable_runtime.py", "src/night.py src/portable_runtime.py")
workflow_path.write_text(workflow)

# Convert FastNight tests into Night fast-path regression tests.
test_old = ROOT / "tests/test_night_fast.py"
test_new = ROOT / "tests/test_fast_paths.py"
test = test_old.read_text()
test = test.replace("from night import MethodNotAllowed, Request\nfrom night_fast import FastNight\n", "from night import MethodNotAllowed, Night, Request\n")
test = test.replace("FastNight()", "Night()")
test = test.replace("app._fast_static[\"GET\"][\"/hello\"]", "app._static_method_index[\"GET\"][\"/hello\"]")
test = test.replace("app._endpoint_plans", "app._endpoint_plans")
test_new.write_text(test)
test_old.unlink()

# Keep a before/after microbenchmark by embedding the legacy dispatch behavior.
bench_path = ROOT / "benchmarks/fast_path.py"
bench = bench_path.read_text()
bench = bench.replace("from night import Night, Request\nfrom night_fast import FastNight\n", "from night import Night, Request\n")
bench = bench.replace("def build(app_type):\n    app = app_type()", "def build(app_type):\n    app = app_type()")
legacy = '''\n\nclass LegacyNight(Night):\n    \"\"\"Pre-fast-path dispatch behavior retained only for microbench comparison.\"\"\"\n\n    def _match_method(self, path: str, method: str):\n        key = path.rstrip(\"/\") or \"/\"\n        candidates = self._static_route_index.get(key)\n        if candidates is None:\n            candidates = self._dynamic_route_index\n        path_matched = False\n        for route in candidates:\n            match = route.pattern.match(path)\n            if not match:\n                continue\n            path_matched = True\n            if method in route.methods:\n                return route, match.groupdict()\n        if path_matched:\n            from night import MethodNotAllowed\n            raise MethodNotAllowed(self._allowed_methods_for_path(path))\n        from night import NotFound\n        raise NotFound()\n\n    async def _call_endpoint(self, fn, req, params):\n        import inspect\n        import typing as t\n        try:\n            sig = inspect.signature(fn)\n        except Exception:\n            sig = None\n        try:\n            type_hints = t.get_type_hints(fn)\n        except Exception:\n            type_hints = {}\n        kwargs = dict(params)\n        if sig is not None:\n            for name, param in sig.parameters.items():\n                if name in kwargs and type_hints.get(name, param.annotation) is int:\n                    try:\n                        kwargs[name] = int(kwargs[name])\n                    except Exception:\n                        pass\n        if sig is not None and \"req\" in sig.parameters:\n            result = fn(req=req, **kwargs)\n        elif sig is not None and sig.parameters:\n            first = next(iter(sig.parameters.values()))\n            if type_hints.get(first.name, first.annotation) is Request or first.name in (\"request\", \"req\"):\n                result = fn(req, **kwargs)\n            else:\n                result = fn(**kwargs)\n        else:\n            result = fn(**kwargs)\n        if inspect.isawaitable(result):\n            result = await result\n        return self._coerce_response(result)\n'''
insert_at = bench.index("\ndef build(app_type):")
bench = bench[:insert_at] + legacy + bench[insert_at:]
bench = bench.replace("for app_type in (Night, FastNight):", "for app_type in (LegacyNight, Night):")
bench = bench.replace('baseline = results["Night"]\n        fast = results["FastNight"]', 'baseline = results["LegacyNight"]\n        fast = results["Night"]')
bench_path.write_text(bench)

for path in [ROOT / "night_fast.py", ROOT / "deploy/cloudflare-night/night_fast.py"]:
    if path.exists():
        path.unlink()

# Remove the one-shot migration machinery from the commit it creates.
self_path = ROOT / "tools/integrate_fastnight.py"
workflow_once = ROOT / ".github/workflows/integrate-fastnight.yml"
if workflow_once.exists():
    workflow_once.unlink()
if self_path.exists():
    self_path.unlink()
