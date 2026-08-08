"""Experimental Night hot-path optimizations.

The fastNight branch keeps these changes isolated until benchmarks show a
repeatable win.  This revision deliberately optimizes only the common single
parameter dynamic-route path and otherwise delegates to Night unchanged.
"""

from __future__ import annotations

from night import Night, Request, Response, ROUTE_CALL_DIRECT_PARAM


class FastNight(Night):
    """Night with a small dynamic-route dispatch shortcut."""

    async def _dispatch(self, req: Request, path: str | None = None,
                        method: str | None = None) -> Response:
        path = req.path if path is None else path
        method = req.method if method is None else method

        # Common API shape: one dynamic route for a method, one <str/int:param>,
        # direct positional handler, and no hooks.  Night already recognizes
        # this shape; here we avoid _match_direct_for_dispatch()'s tuple return
        # and its second layer of branching on the hottest path.
        if not self.before_hooks and not self.after_hooks:
            routes = self._dynamic_method_routes.get(method)
            if routes and len(routes) == 1:
                route = routes[0]
                if (
                    route._night_call_kind == ROUTE_CALL_DIRECT_PARAM
                    and route._night_simple_dynamic is not None
                ):
                    key = path if path == "/" or not path.endswith("/") else path.rstrip("/")
                    value = self._simple_dynamic_value(route, key)
                    if value is not None:
                        req.path_params[route._night_direct_param] = value
                        invoke = route._night_invoke_scalar
                        if route._night_invoke_async:
                            return await invoke(value)
                        return invoke(value)

        return await super()._dispatch(req, path, method)


__all__ = ["FastNight"]
