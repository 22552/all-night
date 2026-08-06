from pathlib import Path
import re

p = Path("night.py")
s = p.read_text()

needle = "MAX_SESSION_COOKIE_SIZE = 3800\n"
if "_NO_PATH_PARAM = object()" not in s:
    if needle not in s:
        raise SystemExit("constants anchor not found")
    s = s.replace(needle, needle + "_NO_PATH_PARAM = object()\n", 1)

# Keep the public/internal compatibility matcher returning dicts, and add a
# scalar matcher used only by production dispatch.
insert_simple = '''    @staticmethod
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

'''
marker = "    @staticmethod\n    def _match_simple_dynamic(route: Route, path: str):\n"
if "def _match_simple_dynamic_value" not in s:
    if marker not in s:
        raise SystemExit("simple matcher marker not found")
    s = s.replace(marker, insert_simple + marker, 1)

insert_fast = '''    def _match_prefixed_dynamic_fast(self, path: str, method: str):
        index = self._dynamic_prefix_index.get(method)
        if not index:
            return None

        # Only return from this fast matcher when the endpoint can consume the
        # converted scalar directly. Other route shapes fall back to the
        # compatibility matcher, which still returns a params dict.
        probe = path
        while True:
            slash = probe.rfind("/")
            if slash <= 0:
                break
            prefix = probe[:slash + 1]
            routes = index.get(prefix)
            if routes:
                for route in routes:
                    if route._night_direct_param is None:
                        continue
                    value = self._match_simple_dynamic_value(route, path)
                    if value is not _NO_PATH_PARAM:
                        return route, value
            probe = probe[:slash]

        routes = index.get("/")
        if routes:
            for route in routes:
                if route._night_direct_param is None:
                    continue
                value = self._match_simple_dynamic_value(route, path)
                if value is not _NO_PATH_PARAM:
                    return route, value
        return None

    def _match_method_fast(self, path: str, method: str) -> tuple[Route, t.Any]:
        key = path.rstrip("/") or "/"

        # Static dispatch needs no path-param container at all.
        route = self._static_method_index.get(method, {}).get(key)
        if route is not None:
            return route, None

        if key in self._static_methods_by_path:
            raise MethodNotAllowed(self._allowed_methods_for_path(path))

        routes = self._dynamic_method_routes.get(method)
        if routes and len(routes) == 1:
            route = routes[0]
            if route._night_simple_dynamic is not None and route._night_direct_param is not None:
                value = self._match_simple_dynamic_value(route, key)
                if value is not _NO_PATH_PARAM:
                    return route, value
        elif routes:
            matched = self._match_prefixed_dynamic_fast(key, method)
            if matched is not None:
                return matched

        # Complex routes, handlers needing request/body injection, and misses
        # retain the exact historical dict-based behavior and error semantics.
        return self._match_method(path, method)

'''
marker = "    def _match_method(self, path: str, method: str) -> tuple[Route, dict[str, t.Any]]:\n"
if "def _match_method_fast" not in s:
    if marker not in s:
        raise SystemExit("match method marker not found")
    s = s.replace(marker, insert_fast + marker, 1)

new_call = '''    async def _call_route(self, route: Route, req: Request, params: t.Any) -> Response:
        plan = route._night_plan
        fn = route.endpoint

        direct_param = getattr(route, "_night_direct_param", None)
        if direct_param is not None and params is not None:
            # Optimized dispatch passes a converted scalar. Compatibility
            # callers can still provide the historical {name: value} dict.
            if isinstance(params, dict):
                result = fn(params[direct_param])
            else:
                result = fn(params)
        elif params is None and plan.body_model is None:
            # Static production dispatch does not allocate an empty params dict.
            if plan.call_mode == CALL_REQUEST_KEYWORD:
                result = fn(req=req)
            elif plan.call_mode == CALL_REQUEST_POSITIONAL:
                result = fn(req)
            else:
                result = fn()
        else:
            kwargs = {} if params is None else params

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

new_dispatch = '''    async def _dispatch(self, req: Request) -> Response:
        early = await self._run_before_hooks(req)
        if early is not None:
            return early

        route, params = self._match_method_fast(req.path, req.method)
        if params is None:
            req.path_params.clear()
        elif isinstance(params, dict):
            req.path_params = params
        else:
            # Reuse the Request's already-allocated path_params dict instead of
            # creating a second temporary dict in the router.
            req.path_params.clear()
            req.path_params[route._night_direct_param] = params

        resp = await self._call_route(route, req, params)
        resp = await self._run_after_hooks(req, resp)
        return resp
'''
pat = re.compile(r'    async def _dispatch\(self, req: Request\) -> Response:\n.*?(?=\n    async def |\n    def )', re.S)
s, n = pat.subn(new_dispatch.rstrip(), s, count=1)
if n != 1:
    raise SystemExit(f"dispatch replacement count={n}")

p.write_text(s)

# Make the internal benchmark exercise the production-only matcher for Night,
# while LegacyNight continues to measure the historical path.
b = Path("benchmarks/fast_path.py")
bs = b.read_text()
old = '''    for _ in range(iterations):
        route, params = app._match_method(path, "GET")
        await app._call_route(route, req, params)
'''
new = '''    matcher = app._match_method if isinstance(app, LegacyNight) else app._match_method_fast
    for _ in range(iterations):
        route, params = matcher(path, "GET")
        await app._call_route(route, req, params)
'''
if old not in bs:
    raise SystemExit("benchmark hot-path block not found")
b.write_text(bs.replace(old, new, 1))
