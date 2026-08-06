from pathlib import Path
import re

p = Path("night.py")
s = p.read_text()

needle = "MAX_SESSION_COOKIE_SIZE = 3800\n"
if "_NO_PATH_PARAM = object()" not in s:
    if needle not in s:
        raise SystemExit("constants anchor not found")
    s = s.replace(needle, needle + "_NO_PATH_PARAM = object()\n", 1)

new_simple = '''    @staticmethod
    def _match_simple_dynamic_value(route: Route, path: str):
        prefix, suffix, _name, converter = route._night_simple_dynamic
        if not path.startswith(prefix):
            return _NO_PATH_PARAM
        if suffix:
            if not path.endswith(suffix):
                return _NO_PATH_PARAM
            value = path[len(prefix):len(path) - len(suffix)]
        else:
            value = path[len(prefix):]
        if not value or "/" in value:
            return _NO_PATH_PARAM
        if converter == "int":
            try:
                return int(value)
            except ValueError:
                return _NO_PATH_PARAM
        return value

    @staticmethod
    def _match_simple_dynamic(route: Route, path: str):
        value = Night._match_simple_dynamic_value(route, path)
        if value is _NO_PATH_PARAM:
            return None
        return {route._night_simple_dynamic[2]: value}
'''
pat = re.compile(r'    @staticmethod\n    def _match_simple_dynamic\(route: Route, path: str\):\n.*?(?=\n    def _match_prefixed_dynamic)', re.S)
s, n = pat.subn(new_simple.rstrip(), s, count=1)
if n != 1:
    raise SystemExit(f"simple matcher replacement count={n}")

new_prefixed = '''    def _match_prefixed_dynamic(self, path: str, method: str):
        index = self._dynamic_prefix_index.get(method)
        if not index:
            return None

        # Probe literal prefixes from longest to shortest. Direct one-parameter
        # handlers carry the raw converted value forward, avoiding a path-param
        # dict allocation on the hottest dynamic route path.
        probe = path
        while True:
            slash = probe.rfind("/")
            if slash <= 0:
                break
            prefix = probe[:slash + 1]
            routes = index.get(prefix)
            if routes:
                for route in routes:
                    value = self._match_simple_dynamic_value(route, path)
                    if value is _NO_PATH_PARAM:
                        continue
                    if route._night_direct_param is not None:
                        return route, value
                    return route, {route._night_simple_dynamic[2]: value}
            probe = probe[:slash]

        routes = index.get("/")
        if routes:
            for route in routes:
                value = self._match_simple_dynamic_value(route, path)
                if value is _NO_PATH_PARAM:
                    continue
                if route._night_direct_param is not None:
                    return route, value
                return route, {route._night_simple_dynamic[2]: value}
        return None
'''
pat = re.compile(r'    def _match_prefixed_dynamic\(self, path: str, method: str\):\n.*?(?=\n    def _rebuild_dynamic_matcher)', re.S)
s, n = pat.subn(new_prefixed.rstrip(), s, count=1)
if n != 1:
    raise SystemExit(f"prefixed matcher replacement count={n}")

new_match = '''    def _match_method(self, path: str, method: str) -> tuple[Route, t.Any]:
        key = path.rstrip("/") or "/"

        route = self._static_method_index.get(method, {}).get(key)
        if route is not None:
            return route, {}

        if key in self._static_methods_by_path:
            raise MethodNotAllowed(self._allowed_methods_for_path(path))

        routes = self._dynamic_method_routes.get(method)

        # One dynamic route is common for tiny services. Direct one-parameter
        # handlers receive the converted scalar itself rather than a temporary
        # {name: value} dict.
        if routes and len(routes) == 1:
            route = routes[0]
            if route._night_simple_dynamic is not None:
                value = self._match_simple_dynamic_value(route, key)
                if value is not _NO_PATH_PARAM:
                    if route._night_direct_param is not None:
                        return route, value
                    return route, {route._night_simple_dynamic[2]: value}
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

new_call = '''    async def _call_route(self, route: Route, req: Request, params: t.Any) -> Response:
        plan = route._night_plan
        fn = route.endpoint

        direct_param = getattr(route, "_night_direct_param", None)
        if direct_param is not None:
            # Normal optimized dispatch passes the raw converted scalar. Keep
            # dict support for compatibility callers that invoke _call_route
            # directly with the historical params representation.
            if isinstance(params, dict):
                result = fn(params[direct_param])
            else:
                result = fn(params)
        else:
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
pat = re.compile(r'    async def _call_route\(self, route: Route, req: Request, params: .*?\) -> Response:\n.*?(?=\n    async def |\n    def )', re.S)
s, n = pat.subn(new_call.rstrip(), s, count=1)
if n != 1:
    raise SystemExit(f"call_route replacement count={n}")

p.write_text(s)
