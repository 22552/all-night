from pathlib import Path

p = Path('night.py')
s = p.read_text()

# Replace async-only compiled invokers with sync invokers for sync endpoints,
# while retaining async invokers only when the endpoint itself is async.
start = s.index('    def _compile_route_invoker(self, route: Route, plan: _EndpointPlan):\n')
end = s.index('    def _on_route_added(self, route: Route):\n', start)
new = '''    def _compile_route_invoker(self, route: Route, plan: _EndpointPlan):
        fn = route.endpoint
        coerce = self._coerce_response
        kind = route._night_call_kind
        route._night_invoke_async = plan.is_coro
        route._night_invoke_scalar = None

        if kind == ROUTE_CALL_DIRECT_PARAM:
            name = route._night_direct_param
            if plan.is_coro:
                async def invoke(req, params, _fn=fn, _name=name, _coerce=coerce):
                    return _coerce(await _fn(params[_name]))
                async def invoke_scalar(value, _fn=fn, _coerce=coerce):
                    return _coerce(await _fn(value))
            else:
                def invoke(req, params, _fn=fn, _name=name, _coerce=coerce):
                    return _coerce(_fn(params[_name]))
                def invoke_scalar(value, _fn=fn, _coerce=coerce):
                    return _coerce(_fn(value))
            route._night_invoke_scalar = invoke_scalar
            return invoke

        if kind == ROUTE_CALL_NOARGS:
            if plan.is_coro:
                async def invoke(req, params, _fn=fn, _coerce=coerce):
                    return _coerce(await _fn())
            else:
                def invoke(req, params, _fn=fn, _coerce=coerce):
                    return _coerce(_fn())
            return invoke

        if kind == ROUTE_CALL_REQUEST_KEYWORD:
            if plan.is_coro:
                async def invoke(req, params, _fn=fn, _coerce=coerce):
                    return _coerce(await _fn(req=req))
            else:
                def invoke(req, params, _fn=fn, _coerce=coerce):
                    return _coerce(_fn(req=req))
            return invoke

        if kind == ROUTE_CALL_REQUEST_POSITIONAL:
            if plan.is_coro:
                async def invoke(req, params, _fn=fn, _coerce=coerce):
                    return _coerce(await _fn(req))
            else:
                def invoke(req, params, _fn=fn, _coerce=coerce):
                    return _coerce(_fn(req))
            return invoke

        route._night_invoke_async = True
        async def invoke(req, params, _route=route):
            return await self._call_route_generic(_route, req, params)
        return invoke

    @staticmethod
    def _simple_dynamic_value(route: Route, path: str):
        prefix, suffix, _name, converter = route._night_simple_dynamic
        if not path.startswith(prefix):
            return None
        if suffix:
            if not path.endswith(suffix):
                return None
            value = path[len(prefix):len(path) - len(suffix)]
        else:
            value = path[len(prefix):]
        if not value or '/' in value:
            return None
        if converter == 'int':
            try:
                value = int(value)
            except ValueError:
                return None
        return value

    def _match_direct_for_dispatch(self, path: str, method: str):
        key = path.rstrip('/') or '/'

        method_routes = self._static_method_index.get(method)
        if method_routes is not None:
            route = method_routes.get(key)
            if route is not None and route._night_call_kind == ROUTE_CALL_NOARGS:
                return route, None

        routes = self._dynamic_method_routes.get(method)
        if routes and len(routes) == 1:
            route = routes[0]
            if route._night_call_kind == ROUTE_CALL_DIRECT_PARAM and route._night_simple_dynamic is not None:
                value = self._simple_dynamic_value(route, key)
                if value is not None:
                    return route, value
        elif routes:
            terminal = self._dynamic_terminal_index.get(method)
            if terminal:
                base, sep, value = key.rpartition('/')
                if sep and value:
                    route = terminal.get(base or '/')
                    if route is not None and route._night_call_kind == ROUTE_CALL_DIRECT_PARAM:
                        _prefix, _suffix, _name, converter = route._night_simple_dynamic
                        if converter == 'int':
                            try:
                                value = int(value)
                            except ValueError:
                                return None
                        return route, value
        return None

'''
s = s[:start] + new + s[end:]

old = '''    async def _dispatch(self, req: Request) -> Response:
        if self.before_hooks:
            early = await self._run_before_hooks(req)
            if early is not None:
                return early

        route, params = self._match_method(req.path, req.method)
        req.path_params = params
        resp = await route._night_invoke(req, params)
        if self.after_hooks:
            resp = await self._run_after_hooks(req, resp)
        return resp
'''
new_dispatch = '''    async def _dispatch(self, req: Request) -> Response:
        if self.before_hooks:
            early = await self._run_before_hooks(req)
            if early is not None:
                return early

        direct = self._match_direct_for_dispatch(req.path, req.method)
        if direct is not None:
            route, value = direct
            if route._night_call_kind == ROUTE_CALL_DIRECT_PARAM:
                name = route._night_direct_param
                req.path_params[name] = value
                invoke = route._night_invoke_scalar
                if route._night_invoke_async:
                    resp = await invoke(value)
                else:
                    resp = invoke(value)
            else:
                invoke = route._night_invoke
                if route._night_invoke_async:
                    resp = await invoke(req, req.path_params)
                else:
                    resp = invoke(req, req.path_params)
        else:
            route, params = self._match_method(req.path, req.method)
            req.path_params = params
            invoke = route._night_invoke
            if route._night_invoke_async:
                resp = await invoke(req, params)
            else:
                resp = invoke(req, params)

        if self.after_hooks:
            resp = await self._run_after_hooks(req, resp)
        return resp
'''
if old not in s:
    raise SystemExit('dispatch anchor missing')
s = s.replace(old, new_dispatch, 1)

# Keep compatibility _call_route able to consume sync or async compiled invokers.
old = '''    async def _call_route(self, route: Route, req: Request, params: dict[str, t.Any]) -> Response:
        invoke = getattr(route, "_night_invoke", None)
        if invoke is None:
            # Compatibility path for synthetic routes used by _call_endpoint().
            return await self._call_route_generic(route, req, params)
        return await invoke(req, params)
'''
new_call = '''    async def _call_route(self, route: Route, req: Request, params: dict[str, t.Any]) -> Response:
        invoke = getattr(route, "_night_invoke", None)
        if invoke is None:
            # Compatibility path for synthetic routes used by _call_endpoint().
            return await self._call_route_generic(route, req, params)
        result = invoke(req, params)
        if getattr(route, "_night_invoke_async", False):
            return await result
        return result
'''
if old not in s:
    raise SystemExit('call_route compatibility anchor missing')
s = s.replace(old, new_call, 1)

p.write_text(s)
