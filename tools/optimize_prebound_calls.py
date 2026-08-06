from pathlib import Path
import re

p = Path("night.py")
s = p.read_text()

anchor = "CALL_REQUEST_KEYWORD = 2\n"
if "ROUTE_CALL_GENERIC" not in s:
    if anchor not in s:
        raise SystemExit("call constants anchor not found")
    s = s.replace(anchor, anchor + "\nROUTE_CALL_GENERIC = 0\nROUTE_CALL_DIRECT_PARAM = 1\nROUTE_CALL_NOARGS = 2\nROUTE_CALL_REQUEST_KEYWORD = 3\nROUTE_CALL_REQUEST_POSITIONAL = 4\n", 1)

marker = "    def _on_route_added(self, route: Route):\n"
helper = '''    @staticmethod
    def _classify_route_call(route: Route, plan: _EndpointPlan) -> None:
        if plan.body_model is not None:
            route._night_call_kind = ROUTE_CALL_GENERIC
            return
        if route._night_direct_param is not None:
            route._night_call_kind = ROUTE_CALL_DIRECT_PARAM
            return
        if plan.call_mode == CALL_REQUEST_KEYWORD:
            route._night_call_kind = ROUTE_CALL_REQUEST_KEYWORD
            return
        if plan.call_mode == CALL_REQUEST_POSITIONAL:
            route._night_call_kind = ROUTE_CALL_REQUEST_POSITIONAL
            return
        sig = plan.signature
        if plan.call_mode == CALL_KWARGS and sig is not None and not sig.parameters:
            route._night_call_kind = ROUTE_CALL_NOARGS
            return
        route._night_call_kind = ROUTE_CALL_GENERIC

'''
if "def _classify_route_call" not in s:
    if marker not in s:
        raise SystemExit("on_route marker not found")
    s = s.replace(marker, helper + marker, 1)

needle = "        route._night_direct_param = None\n\n        if \"<\" in route.raw_path:\n"
replacement = "        route._night_direct_param = None\n        route._night_call_kind = ROUTE_CALL_GENERIC\n\n        if \"<\" in route.raw_path:\n"
if needle not in s:
    raise SystemExit("route init anchor not found")
s = s.replace(needle, replacement, 1)

needle = '''                self._rebuild_dynamic_matcher(method)
            return

        self._static_route_index.setdefault(key, []).append(route)
'''
replacement = '''                self._rebuild_dynamic_matcher(method)
            self._classify_route_call(route, plan)
            return

        self._classify_route_call(route, plan)
        self._static_route_index.setdefault(key, []).append(route)
'''
if needle not in s:
    raise SystemExit("route classification insertion anchor not found")
s = s.replace(needle, replacement, 1)

new_call = '''    async def _call_route(self, route: Route, req: Request, params: dict[str, t.Any]) -> Response:
        plan = route._night_plan
        fn = route.endpoint
        kind = route._night_call_kind

        if kind == ROUTE_CALL_DIRECT_PARAM:
            result = fn(params[route._night_direct_param])
        elif kind == ROUTE_CALL_NOARGS:
            result = fn()
        elif kind == ROUTE_CALL_REQUEST_KEYWORD:
            result = fn(req=req)
        elif kind == ROUTE_CALL_REQUEST_POSITIONAL:
            result = fn(req)
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
pat = re.compile(r'    async def _call_route\(self, route: Route, req: Request, params: dict\[str, t.Any\]\) -> Response:\n.*?(?=\n    async def _call_endpoint)', re.S)
s, n = pat.subn(new_call.rstrip(), s, count=1)
if n != 1:
    raise SystemExit(f"call route replacement count={n}")

old = "        route = types.SimpleNamespace(endpoint=fn, _night_plan=plan)\n"
new = "        route = types.SimpleNamespace(endpoint=fn, _night_plan=plan, _night_direct_param=None, _night_call_kind=ROUTE_CALL_GENERIC)\n        self._classify_route_call(route, plan)\n"
if old not in s:
    raise SystemExit("compat route anchor not found")
s = s.replace(old, new, 1)

p.write_text(s)
