from pathlib import Path
import re

p = Path("night.py")
s = p.read_text()

needle = '''        self._dynamic_method_routes: dict[str, list[Route]] = {}\n        self._dynamic_method_matchers: dict[str, tuple[re.Pattern, list[Route]]] = {}\n'''
replacement = '''        self._dynamic_method_routes: dict[str, list[Route]] = {}\n        self._dynamic_method_matchers: dict[str, tuple[re.Pattern, list[Route]]] = {}\n        self._dynamic_prefix_index: dict[str, dict[str, list[Route]]] = {}\n'''
if needle not in s:
    raise SystemExit("dynamic index init block not found")
s = s.replace(needle, replacement, 1)

old_clear = '''        self._dynamic_method_routes.clear()\n        self._dynamic_method_matchers.clear()\n'''
new_clear = '''        self._dynamic_method_routes.clear()\n        self._dynamic_method_matchers.clear()\n        self._dynamic_prefix_index.clear()\n'''
if old_clear not in s:
    raise SystemExit("dynamic index clear block not found")
s = s.replace(old_clear, new_clear, 1)

new_on_route = '''    def _on_route_added(self, route: Route):
        key = route.raw_path.rstrip("/") or "/"
        plan = _compile_endpoint(route.endpoint)
        self._endpoint_plans[route.endpoint] = plan
        route._night_plan = plan
        route._night_simple_dynamic = None
        route._night_direct_param = None

        if "<" in route.raw_path:
            self._dynamic_route_index.append(route)

            # Common one-parameter routes get a regex-free matcher.
            tokens = list(re.finditer(r"<([^>]+)>", key))
            if len(tokens) == 1:
                token = tokens[0]
                inner = token.group(1)
                if ":" in inner:
                    converter, name = inner.split(":", 1)
                else:
                    converter, name = "str", inner
                if converter in {"str", "int"}:
                    prefix = key[:token.start()]
                    suffix = key[token.end():]
                    route._night_simple_dynamic = (prefix, suffix, name, converter)

                    # For the common def handler(id): case, bypass **kwargs and
                    # call the function positionally. This removes a kwargs
                    # expansion from the hottest dynamic path.
                    sig = plan.signature
                    if plan.call_mode == CALL_KWARGS and plan.body_model is None and sig is not None:
                        ps = tuple(sig.parameters.values())
                        if (
                            len(ps) == 1
                            and ps[0].name == name
                            and ps[0].kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
                        ):
                            route._night_direct_param = name

            for method in route.methods:
                routes = self._dynamic_method_routes.setdefault(method, [])
                routes.append(route)
                if route._night_simple_dynamic is not None:
                    prefix = route._night_simple_dynamic[0]
                    self._dynamic_prefix_index.setdefault(method, {}).setdefault(prefix, []).append(route)
                self._rebuild_dynamic_matcher(method)
            return

        self._static_route_index.setdefault(key, []).append(route)
        methods = self._static_methods_by_path.setdefault(key, set())
        for method in route.methods:
            methods.add(method)
            self._static_method_index.setdefault(method, {})[key] = route
'''
pat = re.compile(r'    def _on_route_added\(self, route: Route\):\n.*?(?=\n    def _rebuild_dynamic_matcher)', re.S)
s, n = pat.subn(new_on_route.rstrip(), s, count=1)
if n != 1:
    raise SystemExit(f"on_route_added replacement count={n}")

helper = '''
    @staticmethod
    def _match_simple_dynamic(route: Route, path: str):
        prefix, suffix, name, converter = route._night_simple_dynamic
        if not path.startswith(prefix):
            return None
        if suffix:
            if not path.endswith(suffix):
                return None
            value = path[len(prefix):len(path) - len(suffix)]
        else:
            value = path[len(prefix):]
        if not value or "/" in value:
            return None
        if converter == "int":
            try:
                value = int(value)
            except ValueError:
                return None
        return {name: value}

    def _match_prefixed_dynamic(self, path: str, method: str):
        index = self._dynamic_prefix_index.get(method)
        if not index:
            return None

        # Probe literal prefixes from longest to shortest. Runtime cost scales
        # with path depth rather than number of routes.
        probe = path
        while True:
            slash = probe.rfind("/")
            if slash <= 0:
                break
            prefix = probe[:slash + 1]
            routes = index.get(prefix)
            if routes:
                for route in routes:
                    params = self._match_simple_dynamic(route, path)
                    if params is not None:
                        return route, params
            probe = probe[:slash]

        routes = index.get("/")
        if routes:
            for route in routes:
                params = self._match_simple_dynamic(route, path)
                if params is not None:
                    return route, params
        return None
'''
marker = '\n    def _rebuild_dynamic_matcher(self, method: str) -> None:'
if marker not in s:
    raise SystemExit("rebuild matcher marker not found")
s = s.replace(marker, helper + marker, 1)

new_match = '''    def _match_method(self, path: str, method: str) -> tuple[Route, dict[str, t.Any]]:
        key = path.rstrip("/") or "/"

        route = self._static_method_index.get(method, {}).get(key)
        if route is not None:
            return route, {}

        if key in self._static_methods_by_path:
            raise MethodNotAllowed(self._allowed_methods_for_path(path))

        routes = self._dynamic_method_routes.get(method)

        # One dynamic route is common for tiny services. Avoid prefix probing
        # and all combined-router machinery in that case.
        if routes and len(routes) == 1:
            route = routes[0]
            if route._night_simple_dynamic is not None:
                params = self._match_simple_dynamic(route, key)
                if params is not None:
                    return route, params
            else:
                match = route.pattern.match(path)
                if match is not None:
                    values = match.groups()
                    params: dict[str, t.Any] = dict(zip(route.param_names, values))
                    plan = route._night_plan
                    for name in plan.int_params:
                        value = params.get(name)
                        if value is not None and type(value) is not int:
                            try:
                                params[name] = int(value)
                            except (TypeError, ValueError):
                                pass
                    return route, params
        else:
            prefixed = self._match_prefixed_dynamic(key, method)
            if prefixed is not None:
                return prefixed

            # Generic fallback only for complex/multi-parameter routes.
            if routes:
                for route in routes:
                    if route._night_simple_dynamic is not None:
                        continue
                    match = route.pattern.match(path)
                    if match is None:
                        continue
                    values = match.groups()
                    params = dict(zip(route.param_names, values))
                    plan = route._night_plan
                    for name in plan.int_params:
                        value = params.get(name)
                        if value is not None and type(value) is not int:
                            try:
                                params[name] = int(value)
                            except (TypeError, ValueError):
                                pass
                    return route, params

        allowed = self._allowed_methods_for_path(path)
        if allowed:
            raise MethodNotAllowed(allowed)
        raise NotFound()
'''
pat = re.compile(r'    def _match_method\(self, path: str, method: str\).*?(?=\n    def )', re.S)
s, n = pat.subn(new_match.rstrip(), s, count=1)
if n != 1:
    raise SystemExit(f"match_method replacement count={n}")

new_call = '''    async def _call_route(self, route: Route, req: Request, params: dict[str, t.Any]) -> Response:
        plan = route._night_plan
        fn = route.endpoint

        direct_param = getattr(route, "_night_direct_param", None)
        if direct_param is not None:
            result = fn(params[direct_param])
        else:
            # params is freshly allocated by routing in normal dispatch, so do
            # not copy it. Compatibility callers still receive equivalent
            # behavior because only body validation mutates kwargs.
            kwargs = params

            if plan.body_model is not None:
                payload = await req.json()
                validated = _validate_dataclass(plan.body_model, payload)
                target = next((name for name in plan.body_candidates if name not in kwargs), None)
                if target is not None:
                    kwargs[target] = validated
                else:
                    kwargs.setdefault("data", validated)

            if plan.call_mode == CALL_REQUEST_KEYWORD:
                result = fn(req=req, **kwargs)
            elif plan.call_mode == CALL_REQUEST_POSITIONAL:
                result = fn(req, **kwargs)
            elif kwargs:
                result = fn(**kwargs)
            else:
                result = fn()

        if plan.is_coro:
            result = await t.cast(t.Awaitable, result)
        return self._coerce_response(result)
'''
pat = re.compile(r'    async def _call_route\(self, route: Route, req: Request, params: dict\[str, t.Any\]\) -> Response:\n.*?(?=\n    async def |\n    def )', re.S)
s, n = pat.subn(new_call.rstrip(), s, count=1)
if n != 1:
    raise SystemExit(f"call_route replacement count={n}")

p.write_text(s)
