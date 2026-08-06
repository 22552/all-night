from pathlib import Path

p = Path('night.py')
s = p.read_text()

s = s.replace(
'''@dataclasses.dataclass(frozen=True, slots=True)
class _EndpointPlan:
    signature: inspect.Signature | None
    type_hints: dict[str, t.Any]
    call_mode: int
    int_params: tuple[str, ...]
    body_model: type | None
    body_candidates: tuple[str, ...]
''',
'''@dataclasses.dataclass(frozen=True, slots=True)
class _EndpointPlan:
    signature: inspect.Signature | None
    type_hints: dict[str, t.Any]
    call_mode: int
    is_coro: bool
    int_params: tuple[str, ...]
    body_model: type | None
    body_candidates: tuple[str, ...]
''')

s = s.replace(
'''    return _EndpointPlan(
        signature=signature,
        type_hints=type_hints,
        call_mode=call_mode,
        int_params=tuple(int_params),
        body_model=getattr(fn, "__night_body_model__", None),
        body_candidates=tuple(body_candidates),
    )
''',
'''    return _EndpointPlan(
        signature=signature,
        type_hints=type_hints,
        call_mode=call_mode,
        is_coro=inspect.iscoroutinefunction(fn),
        int_params=tuple(int_params),
        body_model=getattr(fn, "__night_body_model__", None),
        body_candidates=tuple(body_candidates),
    )
''')

s = s.replace(
'''        self._dynamic_route_index: list[Route] = []
        self._static_method_index: dict[str, dict[str, Route]] = {}
        self._static_methods_by_path: dict[str, set[str]] = {}
        self._endpoint_plans: dict[t.Callable, _EndpointPlan] = {}
''',
'''        self._dynamic_route_index: list[Route] = []
        self._dynamic_method_routes: dict[str, list[Route]] = {}
        self._dynamic_method_matchers: dict[str, tuple[re.Pattern, list[Route]]] = {}
        self._static_method_index: dict[str, dict[str, Route]] = {}
        self._static_methods_by_path: dict[str, set[str]] = {}
        self._endpoint_plans: dict[t.Callable, _EndpointPlan] = {}
''')

old = '''    def _on_route_added(self, route: Route):
        key = route.raw_path.rstrip("/") or "/"
        self._endpoint_plans[route.endpoint] = _compile_endpoint(route.endpoint)
        if "<" in route.raw_path:
            self._dynamic_route_index.append(route)
            return

        self._static_route_index.setdefault(key, []).append(route)
        methods = self._static_methods_by_path.setdefault(key, set())
        for method in route.methods:
            methods.add(method)
            self._static_method_index.setdefault(method, {})[key] = route
'''
new = '''    def _on_route_added(self, route: Route):
        key = route.raw_path.rstrip("/") or "/"
        plan = _compile_endpoint(route.endpoint)
        self._endpoint_plans[route.endpoint] = plan
        route._night_plan = plan
        if "<" in route.raw_path:
            self._dynamic_route_index.append(route)
            for method in route.methods:
                routes = self._dynamic_method_routes.setdefault(method, [])
                routes.append(route)
                self._rebuild_dynamic_matcher(method)
            return

        self._static_route_index.setdefault(key, []).append(route)
        methods = self._static_methods_by_path.setdefault(key, set())
        for method in route.methods:
            methods.add(method)
            self._static_method_index.setdefault(method, {})[key] = route

    def _rebuild_dynamic_matcher(self, method: str) -> None:
        routes = self._dynamic_method_routes.get(method, ())
        if len(routes) < 2:
            self._dynamic_method_matchers.pop(method, None)
            return
        branches = []
        for route in routes:
            body = route.pattern.pattern
            if body.startswith("^"):
                body = body[1:]
            if body.endswith("$"):
                body = body[:-1]
            # Combined matcher only selects the route. Parameter extraction is
            # done once with the selected route's original compiled regex.
            body = re.sub(r"\\(\\?P<[^>]+>", "(?:", body)
            branches.append(f"({body})")
        self._dynamic_method_matchers[method] = (re.compile("^(?:" + "|".join(branches) + ")$"), list(routes))
'''
if old not in s:
    raise SystemExit('on_route_added block not found')
s = s.replace(old, new)

s = s.replace(
'''        self._dynamic_route_index.clear()
        self._static_method_index.clear()
        self._static_methods_by_path.clear()
        self._endpoint_plans.clear()
''',
'''        self._dynamic_route_index.clear()
        self._dynamic_method_routes.clear()
        self._dynamic_method_matchers.clear()
        self._static_method_index.clear()
        self._static_methods_by_path.clear()
        self._endpoint_plans.clear()
''')

old = '''    def _match_method(self, path: str, method: str) -> tuple[Route, dict[str, str]]:
        key = path.rstrip("/") or "/"

        # Hono-style hot path: exact static routes are two hash lookups and
        # avoid regex matching entirely. Dynamic routes use the proven matcher.
        route = self._static_method_index.get(method, {}).get(key)
        if route is not None:
            return route, {}

        if key in self._static_methods_by_path:
            raise MethodNotAllowed(self._allowed_methods_for_path(path))

        path_matched = False
        for route in self._dynamic_route_index:
            match = route.pattern.match(path)
            if not match:
                continue
            path_matched = True
            if method in route.methods:
                return route, match.groupdict()
        if path_matched:
            raise MethodNotAllowed(self._allowed_methods_for_path(path))
        raise NotFound()
'''
new = '''    def _match_method(self, path: str, method: str) -> tuple[Route, dict[str, t.Any]]:
        key = path.rstrip("/") or "/"

        route = self._static_method_index.get(method, {}).get(key)
        if route is not None:
            return route, {}

        if key in self._static_methods_by_path:
            raise MethodNotAllowed(self._allowed_methods_for_path(path))

        routes = self._dynamic_method_routes.get(method)
        if routes:
            if len(routes) == 1:
                route = routes[0]
                match = route.pattern.match(path)
            else:
                combined, indexed_routes = self._dynamic_method_matchers[method]
                selected = combined.match(path)
                if selected is None:
                    match = None
                    route = None
                else:
                    route = indexed_routes[(selected.lastindex or 1) - 1]
                    match = route.pattern.match(path)

            if route is not None and match is not None:
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

        allowed = self._allowed_methods_for_path(path)
        if allowed:
            raise MethodNotAllowed(allowed)
        raise NotFound()
'''
if old not in s:
    raise SystemExit('match_method block not found')
s = s.replace(old, new)

old = '''    def _coerce_response(self, value: t.Any) -> Response:
        if isinstance(value, Response):
            return value
        if isinstance(value, (dict, list)):
            return JSONResponse(value)
        if isinstance(value, str):
            return PlainTextResponse(value)
        if isinstance(value, (bytes, bytearray)):
            return Response(value)
        if value is None:
            return Response(b"", status=204)
        return PlainTextResponse(str(value))
'''
new = '''    def _coerce_response(self, value: t.Any) -> Response:
        kind = type(value)
        if kind is dict or kind is list:
            return JSONResponse(value)
        if kind is str:
            return PlainTextResponse(value)
        if kind is bytes:
            return Response(value)
        if value is None:
            return Response(b"", status=204)
        if isinstance(value, Response):
            return value
        if kind is bytearray:
            return Response(value)
        return PlainTextResponse(str(value))
'''
if old not in s:
    raise SystemExit('coerce block not found')
s = s.replace(old, new)

old = '''    async def _call_endpoint(self, fn: t.Callable, req: Request, params: dict[str, str]) -> Response:
        plan = self._endpoint_plans.get(fn)
        if plan is None:
            plan = _compile_endpoint(fn)
            self._endpoint_plans[fn] = plan

        kwargs: dict[str, t.Any] = dict(params)

        if plan.body_model is not None:
            payload = await req.json()
            validated = _validate_dataclass(plan.body_model, payload)
            target = next((name for name in plan.body_candidates if name not in kwargs), None)
            if target is not None:
                kwargs[target] = validated
            else:
                kwargs.setdefault("data", validated)

        for name in plan.int_params:
            if name in kwargs and not isinstance(kwargs[name], int):
                try:
                    kwargs[name] = int(kwargs[name])
                except (TypeError, ValueError):
                    pass

        if plan.call_mode == CALL_REQUEST_KEYWORD:
            result = fn(req=req, **kwargs)
        elif plan.call_mode == CALL_REQUEST_POSITIONAL:
            result = fn(req, **kwargs)
        else:
            result = fn(**kwargs)

        if inspect.isawaitable(result):
            result = await t.cast(t.Awaitable, result)
        return self._coerce_response(result)
'''
new = '''    async def _call_route(self, route: Route, req: Request, params: dict[str, t.Any]) -> Response:
        plan = route._night_plan
        kwargs = params.copy() if params else {}

        if plan.body_model is not None:
            payload = await req.json()
            validated = _validate_dataclass(plan.body_model, payload)
            target = next((name for name in plan.body_candidates if name not in kwargs), None)
            if target is not None:
                kwargs[target] = validated
            else:
                kwargs.setdefault("data", validated)

        fn = route.endpoint
        if plan.call_mode == CALL_REQUEST_KEYWORD:
            result = fn(req=req, **kwargs)
        elif plan.call_mode == CALL_REQUEST_POSITIONAL:
            result = fn(req, **kwargs)
        else:
            result = fn(**kwargs)

        if plan.is_coro:
            result = await t.cast(t.Awaitable, result)
        return self._coerce_response(result)

    async def _call_endpoint(self, fn: t.Callable, req: Request, params: dict[str, t.Any]) -> Response:
        # Compatibility wrapper for code that used this internal helper.
        plan = self._endpoint_plans.get(fn)
        if plan is None:
            plan = _compile_endpoint(fn)
            self._endpoint_plans[fn] = plan
        route = type("_EndpointRoute", (), {"endpoint": fn, "_night_plan": plan})()
        for name in plan.int_params:
            value = params.get(name)
            if value is not None and type(value) is not int:
                try:
                    params[name] = int(value)
                except (TypeError, ValueError):
                    pass
        return await self._call_route(route, req, params)
'''
if old not in s:
    raise SystemExit('call_endpoint block not found')
s = s.replace(old, new)

s = s.replace(
'''        resp = await self._call_endpoint(route.endpoint, req, params)
''',
'''        resp = await self._call_route(route, req, params)
''')

p.write_text(s)
