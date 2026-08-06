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

        if "<" in route.raw_path:
            self._dynamic_route_index.append(route)

            # Common dynamic routes get a regex-free matcher.  Keep the generic
            # regex router as a fallback for multi-parameter/path converters.
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
            end = len(path) - len(suffix)
            value = path[len(prefix):end]
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

        # Probe literal prefixes from longest to shortest.  Runtime cost scales
        # with path depth, not with the number of registered routes.
        probe = path
        seen: set[str] = set()
        while True:
            slash = probe.rfind("/")
            if slash <= 0:
                break
            prefix = probe[:slash + 1]
            if prefix not in seen:
                seen.add(prefix)
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

        prefixed = self._match_prefixed_dynamic(key, method)
        if prefixed is not None:
            return prefixed

        # Generic fallback for complex/multi-parameter dynamic routes.  Simple
        # routes were already handled above, so they do not pay regex cost.
        routes = self._dynamic_method_routes.get(method)
        if routes:
            complex_routes = [r for r in routes if r._night_simple_dynamic is None]
            if len(complex_routes) == 1:
                route = complex_routes[0]
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
            elif complex_routes:
                for route in complex_routes:
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

p.write_text(s)
