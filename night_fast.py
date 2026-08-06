from __future__ import annotations

"""Experimental Hono-inspired fast paths for Night.

This module keeps Night's public route API but moves expensive endpoint
introspection to route-registration time and gives static routes a direct
method -> path lookup. Dynamic routes intentionally fall back to Night's
existing matcher so behavior stays compatible while the hot path is tested.
"""

from dataclasses import dataclass
import inspect
import typing as t

from night import (
    HTTPError,
    MethodNotAllowed,
    Night,
    NotFound,
    Request,
    Response,
    _validate_dataclass,
)


CALL_KWARGS = 0
CALL_REQUEST_POSITIONAL = 1
CALL_REQUEST_KEYWORD = 2


@dataclass(frozen=True, slots=True)
class _EndpointPlan:
    signature: inspect.Signature | None
    type_hints: dict[str, t.Any]
    call_mode: int
    int_params: tuple[str, ...]
    body_model: type | None
    body_candidates: tuple[str, ...]


def _compile_endpoint(fn: t.Callable) -> _EndpointPlan:
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        signature = None

    try:
        type_hints = t.get_type_hints(fn)
    except Exception:
        type_hints = {}

    call_mode = CALL_KWARGS
    int_params: list[str] = []
    body_candidates: list[str] = []

    if signature is not None:
        params = tuple(signature.parameters.values())
        if "req" in signature.parameters:
            call_mode = CALL_REQUEST_KEYWORD
        elif params:
            first = params[0]
            first_type = type_hints.get(first.name, first.annotation)
            if first_type is Request or first.name in {"request", "req"}:
                call_mode = CALL_REQUEST_POSITIONAL

        for param in params:
            annotation = type_hints.get(param.name, param.annotation)
            if annotation is int:
                int_params.append(param.name)
            if param.name not in {"req", "request"}:
                body_candidates.append(param.name)

    return _EndpointPlan(
        signature=signature,
        type_hints=type_hints,
        call_mode=call_mode,
        int_params=tuple(int_params),
        body_model=getattr(fn, "__night_body_model__", None),
        body_candidates=tuple(body_candidates),
    )


class FastNight(Night):
    """Night with low-overhead hot paths inspired by Hono's router design.

    Current optimizations:
    - static route lookup is ``method -> normalized path -> Route``;
    - endpoint signatures and type hints are compiled once at registration;
    - dynamic routes use the existing Night matcher as a compatibility fallback.

    The class is intentionally experimental so it can be benchmarked before
    these fast paths are folded into ``Night`` itself.
    """

    def __init__(self, *args: t.Any, **kwargs: t.Any):
        self._fast_static: dict[str, dict[str, t.Any]] = {}
        self._fast_static_methods: dict[str, set[str]] = {}
        self._endpoint_plans: dict[t.Callable, _EndpointPlan] = {}
        super().__init__(*args, **kwargs)

    def _on_route_added(self, route):
        super()._on_route_added(route)
        self._endpoint_plans[route.endpoint] = _compile_endpoint(route.endpoint)

        if "<" in route.raw_path:
            return

        key = route.raw_path.rstrip("/") or "/"
        methods = self._fast_static_methods.setdefault(key, set())
        for method in route.methods:
            methods.add(method)
            self._fast_static.setdefault(method, {})[key] = route

    def _allowed_methods_for_path(self, path: str) -> set[str]:
        key = path.rstrip("/") or "/"
        methods = self._fast_static_methods.get(key)
        if methods is not None:
            result = set(methods)
            if "GET" in result:
                result.add("HEAD")
            return result
        return super()._allowed_methods_for_path(path)

    def _match_method(self, path: str, method: str):
        key = path.rstrip("/") or "/"
        route = self._fast_static.get(method, {}).get(key)
        if route is not None:
            return route, {}

        static_methods = self._fast_static_methods.get(key)
        if static_methods is not None:
            raise MethodNotAllowed(self._allowed_methods_for_path(path))

        # Hono's SmartRouter idea, conservatively applied: take the O(1)
        # static fast path first, then fall back to Night's proven dynamic
        # matcher for routes that need regex captures.
        return super()._match_method(path, method)

    async def _call_endpoint(self, fn: t.Callable, req: Request, params: dict[str, str]) -> Response:
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


__all__ = ["FastNight"]
