"""Experimental hybrid UI expressions for Midnight.

Normal Python operations keep Python semantics and are evaluated on the server.
Expressions rooted at ``js`` are explicitly evaluated in the browser.

Example::

    from night_midnight_hybrid import HybridMidnight, js

    midnight = HybridMidnight()
    count = midnight.get("#count")

    count.value = count.value + "!"          # browser read -> Python + -> browser set
    count.value = js.Number(count.value) + 1 # entirely browser-side

This module intentionally avoids translating ordinary Python operations to
JavaScript. ``js`` is an execution marker, not merely a namespace alias.
"""

from __future__ import annotations

import operator
import typing as t

from night_midnight import Midnight


_JSON_SCALAR = str | int | float | bool | None


class HybridExpressionError(RuntimeError):
    """Raised when a hybrid expression cannot be represented safely."""


class _ServerExpr:
    __slots__ = ("node",)

    def __init__(self, node: tuple[t.Any, ...]) -> None:
        self.node = node

    def _binary(self, op: str, other: t.Any) -> "_ServerExpr":
        return _ServerExpr(("binary", op, self, other))

    def _rbinary(self, op: str, other: t.Any) -> "_ServerExpr":
        return _ServerExpr(("binary", op, other, self))

    def __add__(self, other: t.Any): return self._binary("add", other)
    def __radd__(self, other: t.Any): return self._rbinary("add", other)
    def __sub__(self, other: t.Any): return self._binary("sub", other)
    def __rsub__(self, other: t.Any): return self._rbinary("sub", other)
    def __mul__(self, other: t.Any): return self._binary("mul", other)
    def __rmul__(self, other: t.Any): return self._rbinary("mul", other)
    def __truediv__(self, other: t.Any): return self._binary("truediv", other)
    def __rtruediv__(self, other: t.Any): return self._rbinary("truediv", other)
    def __floordiv__(self, other: t.Any): return self._binary("floordiv", other)
    def __rfloordiv__(self, other: t.Any): return self._rbinary("floordiv", other)
    def __mod__(self, other: t.Any): return self._binary("mod", other)
    def __rmod__(self, other: t.Any): return self._rbinary("mod", other)
    def __pow__(self, other: t.Any): return self._binary("pow", other)
    def __rpow__(self, other: t.Any): return self._rbinary("pow", other)


class DOMValue(_ServerExpr):
    """A browser DOM property that becomes a Python-side input by default."""

    __slots__ = ("owner", "selector", "property")

    def __init__(self, owner: "HybridMidnight", selector: str, property: str) -> None:
        self.owner = owner
        self.selector = str(selector)
        self.property = str(property)
        super().__init__(("dom", self.selector, self.property))

    def __repr__(self) -> str:
        return f"<DOMValue {self.selector!r}.{self.property}>"


class ClientExpr:
    """Expression explicitly marked for JavaScript/browser evaluation."""

    __slots__ = ("node",)

    def __init__(self, node: dict[str, t.Any]) -> None:
        self.node = node

    def _binary(self, op: str, other: t.Any) -> "ClientExpr":
        return ClientExpr({"kind": "binary", "op": op, "left": self.node, "right": _client_node(other)})

    def _rbinary(self, op: str, other: t.Any) -> "ClientExpr":
        return ClientExpr({"kind": "binary", "op": op, "left": _client_node(other), "right": self.node})

    def __add__(self, other: t.Any): return self._binary("add", other)
    def __radd__(self, other: t.Any): return self._rbinary("add", other)
    def __sub__(self, other: t.Any): return self._binary("sub", other)
    def __rsub__(self, other: t.Any): return self._rbinary("sub", other)
    def __mul__(self, other: t.Any): return self._binary("mul", other)
    def __rmul__(self, other: t.Any): return self._rbinary("mul", other)
    def __truediv__(self, other: t.Any): return self._binary("div", other)
    def __rtruediv__(self, other: t.Any): return self._rbinary("div", other)
    def __mod__(self, other: t.Any): return self._binary("mod", other)
    def __rmod__(self, other: t.Any): return self._rbinary("mod", other)
    def __pow__(self, other: t.Any): return self._binary("pow", other)
    def __rpow__(self, other: t.Any): return self._rbinary("pow", other)


class JSRef(ClientExpr):
    """Reference into ``globalThis``. Attribute access stays symbolic."""

    __slots__ = ("path",)

    def __init__(self, path: tuple[str, ...]) -> None:
        self.path = path
        super().__init__({"kind": "js_ref", "path": list(path)})

    def __getattr__(self, name: str) -> "JSRef":
        if name.startswith("_"):
            raise AttributeError(name)
        return JSRef((*self.path, name))

    def __call__(self, *args: t.Any) -> ClientExpr:
        return ClientExpr({
            "kind": "call",
            "callee": self.node,
            "args": [_client_node(arg) for arg in args],
        })

    def __repr__(self) -> str:
        return "js" + ("." + ".".join(self.path) if self.path else "")


js = JSRef(())


def _client_node(value: t.Any) -> dict[str, t.Any]:
    if isinstance(value, ClientExpr):
        return value.node
    if isinstance(value, DOMValue):
        return {"kind": "dom", "selector": value.selector, "property": value.property}
    if isinstance(value, _ServerExpr):
        raise HybridExpressionError("server/Python expressions cannot be embedded inside js expressions")
    if isinstance(value, (str, int, float, bool)) or value is None:
        return {"kind": "literal", "value": value}
    if isinstance(value, (list, tuple)):
        return {"kind": "literal", "value": list(value)}
    if isinstance(value, dict):
        return {"kind": "literal", "value": dict(value)}
    raise HybridExpressionError(f"{type(value).__name__} is not serializable into a client expression")


class DOMRef:
    """Symbolic browser element returned by :meth:`HybridMidnight.get`."""

    __slots__ = ("_owner", "_selector")

    def __init__(self, owner: "HybridMidnight", selector: str) -> None:
        object.__setattr__(self, "_owner", owner)
        object.__setattr__(self, "_selector", str(selector))

    @property
    def selector(self) -> str:
        return self._selector

    def __getattr__(self, name: str) -> DOMValue:
        if name.startswith("_"):
            raise AttributeError(name)
        return DOMValue(self._owner, self._selector, name)

    def __setattr__(self, name: str, value: t.Any) -> None:
        if name.startswith("_"):
            object.__setattr__(self, name, value)
            return
        if isinstance(value, ClientExpr):
            self._owner._push(
                "hybrid_client_set",
                selector=self._selector,
                property=str(name),
                expr=value.node,
            )
            return
        if isinstance(value, _ServerExpr):
            self._owner._queue_server_set(self._selector, str(name), value)
            return
        self._owner._push("dom_set", selector=self._selector, property=str(name), value=value)

    def __repr__(self) -> str:
        return f"<DOMRef {self._selector!r}>"


_SERVER_BINARY: dict[str, t.Callable[[t.Any, t.Any], t.Any]] = {
    "add": operator.add,
    "sub": operator.sub,
    "mul": operator.mul,
    "truediv": operator.truediv,
    "floordiv": operator.floordiv,
    "mod": operator.mod,
    "pow": operator.pow,
}


def _compile_server(value: t.Any, reads: list[dict[str, str]]) -> tuple[t.Any, ...]:
    if isinstance(value, DOMValue):
        index = len(reads)
        reads.append({"selector": value.selector, "property": value.property})
        return ("input", index)
    if isinstance(value, _ServerExpr):
        kind, *parts = value.node
        if kind == "binary":
            op, left, right = parts
            return ("binary", op, _compile_server(left, reads), _compile_server(right, reads))
        if kind == "dom":
            selector, prop = parts
            index = len(reads)
            reads.append({"selector": str(selector), "property": str(prop)})
            return ("input", index)
        raise HybridExpressionError(f"unknown server expression node: {kind}")
    if isinstance(value, ClientExpr):
        raise HybridExpressionError("js/client expressions must stay entirely client-side")
    return ("literal", value)


def _eval_server(plan: tuple[t.Any, ...], values: list[t.Any]) -> t.Any:
    kind = plan[0]
    if kind == "literal":
        return plan[1]
    if kind == "input":
        return values[int(plan[1])]
    if kind == "binary":
        op = str(plan[1])
        fn = _SERVER_BINARY.get(op)
        if fn is None:
            raise HybridExpressionError(f"unsupported Python operation: {op}")
        return fn(_eval_server(plan[2], values), _eval_server(plan[3], values))
    raise HybridExpressionError(f"unknown server plan node: {kind}")


class HybridMidnight(Midnight):
    """Midnight with explicit Python/browser hybrid DOM expressions."""

    def __init__(self, *args: t.Any, **kwargs: t.Any) -> None:
        super().__init__(*args, **kwargs)
        self._hybrid_pending: dict[tuple[str, int], tuple[str, str, tuple[t.Any, ...]]] = {}
        self._hybrid_sequence = 0

    def get(self, selector: str) -> DOMRef:
        return DOMRef(self, selector)

    def _queue_server_set(self, selector: str, property: str, expr: _ServerExpr) -> None:
        reads: list[dict[str, str]] = []
        plan = _compile_server(expr, reads)
        self._hybrid_sequence += 1
        request_id = self._hybrid_sequence
        key = (self.session_id, request_id)
        self._hybrid_pending[key] = (str(selector), str(property), plan)
        self._push("hybrid_server_set", request_id=request_id, reads=reads)

    def _resolve_hybrid_result(self, payload: dict[str, t.Any]) -> None:
        detail = payload.get("detail") if isinstance(payload, dict) else None
        if not isinstance(detail, dict):
            return
        try:
            request_id = int(detail.get("request_id"))
        except (TypeError, ValueError):
            return
        pending = self._hybrid_pending.pop((self.session_id, request_id), None)
        if pending is None:
            return
        selector, prop, plan = pending
        values = detail.get("values")
        if not isinstance(values, list):
            values = []
        try:
            result = _eval_server(plan, values)
        except Exception as exc:
            self._push(
                "hybrid_error",
                request_id=request_id,
                error_type=type(exc).__name__,
                message=str(exc),
            )
            return
        self._push("dom_set", selector=selector, property=prop, value=result)

    async def _dispatch_current(self, payload: dict[str, t.Any]) -> list[dict[str, t.Any]]:
        if isinstance(payload, dict) and str(payload.get("type", "")) == "custom:__hybrid_result":
            self._resolve_hybrid_result(payload)
            return self.drain()
        return await super()._dispatch_current(payload)


def get(selector: str, *, midnight: HybridMidnight | None = None) -> DOMRef:
    """Convenience DOM selector for an explicit :class:`HybridMidnight` instance."""
    if midnight is None:
        raise RuntimeError("get() needs midnight=...; prefer midnight.get(selector)")
    return midnight.get(selector)


__all__ = [
    "ClientExpr",
    "DOMRef",
    "DOMValue",
    "HybridExpressionError",
    "HybridMidnight",
    "JSRef",
    "get",
    "js",
]
