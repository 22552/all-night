"""Experimental Night optimizations for benchmarking on the fastNight branch.

The public Night API stays intact.  FastNight isolates several conservative
optimizations so each can be measured before anything is moved into night.py:

* skip construction of the currently-unused combined dynamic-route matcher
* fast-path template expressions without filters
* parse template expression ASTs at template compile time and cache them
* avoid an empty-header dict-comprehension in Response.__init__
* avoid Request.state setdefault on repeated accesses
"""

from __future__ import annotations

import ast
import typing as t

import night as _night
from night import Night, Request, Response, Template, TemplateEngine, TemplateError, _TemplateExpression


# ---------------------------------------------------------------------------
# Small process-local patches.  Importing fastnight is explicitly opt-in and
# benchmark servers run it in a separate process from the normal Night server.
# ---------------------------------------------------------------------------

_ORIGINAL_RESPONSE_INIT = Response.__init__
_ORIGINAL_STATE_PROPERTY = Request.state
_PATCHED = False


def _fast_response_init(
    self,
    body: t.Union[str, bytes, bytearray] = b"",
    status: int = 200,
    headers: t.Mapping[str, str] | None = None,
    content_type: str | None = None,
    raw_headers: t.Iterable[tuple[str, str]] | None = None,
):
    """Response.__init__ with an explicit empty-headers fast path.

    Semantics intentionally mirror Night's implementation.  The only hot-path
    difference is avoiding a dict comprehension when headers is None/empty.
    """
    self.status = int(status)
    self.body = _night._to_bytes(body)
    if headers:
        self.headers = {k.lower(): v for k, v in headers.items()}
    else:
        self.headers = {}
    self.raw_headers = list(raw_headers or ())
    if content_type is not None:
        self.headers["content-type"] = content_type
    if "date" not in self.headers:
        self.headers["date"] = _night._cached_http_date()
    if "content-length" not in self.headers:
        self.headers["content-length"] = str(len(self.body))


def _fast_state(self: Request) -> dict:
    """Avoid setdefault when the usual state dict already exists."""
    st = self.scope.get("state")
    if type(st) is dict:
        return st
    if st is None:
        st = {}
        self.scope["state"] = st
        return st
    # Preserve Night's behavior for a non-dict ASGI state value.
    st = {}
    self.scope["state"] = st
    return st


def _install_process_patches() -> None:
    global _PATCHED
    if _PATCHED:
        return
    Response.__init__ = _fast_response_init
    Request.state = property(_fast_state)
    _PATCHED = True


class FastTemplateEngine(TemplateEngine):
    """TemplateEngine that compiles expression ASTs once per template.

    The normal node representation is deliberately unchanged, preserving
    subclass compatibility.  compile() walks the parsed node tree and warms an
    expression cache; render-time evaluate() only creates the lightweight
    visitor and visits the already-parsed AST node.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._expression_cache: dict[str, tuple[str, ast.AST, tuple[str, ...]]] = {}

    def _split_filters(self, expression: str) -> list[str]:
        # Common case: no filters.  str.__contains__ runs in C and avoids the
        # Python character-by-character parser entirely.
        if "|" not in expression:
            expression = expression.strip()
            return [expression] if expression else []
        return super()._split_filters(expression)

    def _compile_expression(self, expression: str):
        cached = self._expression_cache.get(expression)
        if cached is not None:
            return cached
        pipeline = self._split_filters(expression)
        if not pipeline:
            compiled = ("", ast.Constant(value=""), ())
            self._expression_cache[expression] = compiled
            return compiled
        base = pipeline[0]
        try:
            node = ast.parse(base, mode="eval").body
        except SyntaxError as exc:
            raise TemplateError(f"Invalid template expression: {base!r}") from exc
        compiled = (base, node, tuple(pipeline[1:]))
        self._expression_cache[expression] = compiled
        return compiled

    def _warm_nodes(self, nodes) -> None:
        for node in nodes:
            kind = node[0]
            if kind == "expr":
                self._compile_expression(node[1])
            elif kind == "if":
                branches, otherwise = node[1], node[2]
                for condition, body in branches:
                    self._compile_expression(condition)
                    self._warm_nodes(body)
                self._warm_nodes(otherwise)
            elif kind == "for":
                _targets, expression, body, otherwise = node[1:]
                self._compile_expression(expression)
                self._warm_nodes(body)
                self._warm_nodes(otherwise)
            elif kind == "include":
                self._compile_expression(node[1])

    def compile(self, source: str, *, name: str = "<string>") -> Template:
        template = super().compile(source, name=name)
        self._warm_nodes(template.nodes)
        return template

    def evaluate(self, expression: str, context: t.Mapping[str, t.Any]) -> tuple[str, t.Any]:
        base, node, filters = self._compile_expression(expression)
        if not base:
            return "", ""
        value = _TemplateExpression(context).visit(node)
        for name in filters:
            fn = self.filters.get(name)
            if fn is None:
                raise TemplateError(f"Unknown template filter: {name}")
            value = fn(value)
        return base, value


class FastNight(Night):
    """Night with experimental low-risk hot-path optimizations."""

    def __init__(self, *args, **kwargs):
        _install_process_patches()
        template_folder = kwargs.get("template_folder", "templates")
        super().__init__(*args, **kwargs)
        self.template_engine = FastTemplateEngine(template_folder=template_folder)

    def _rebuild_dynamic_matcher(self, method: str) -> None:
        # `_dynamic_method_matchers` is currently not consumed by dispatch.
        # Keeping this as a no-op removes O(n) regex rebuild work on every
        # dynamic route registration without changing request matching.
        self._dynamic_method_matchers.pop(method, None)


__all__ = ["FastNight", "FastTemplateEngine"]
