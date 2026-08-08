from pathlib import Path
import re

night_path = Path("night.py")
text = night_path.read_text(encoding="utf-8")


def replace_once(old: str, new: str, marker: str) -> None:
    global text
    if old in text:
        text = text.replace(old, new, 1)
    elif marker in text:
        print(f"already applied: {marker}")
    else:
        raise SystemExit(f"patch anchor not found: {marker}")


def remove_once(old: str, label: str) -> None:
    global text
    if old in text:
        text = text.replace(old, "", 1)
    else:
        print(f"already absent: {label}")


# 1) Remove the combined dynamic matcher. Dispatch never consumes it, while
# rebuilding it after every dynamic route makes registration O(n^2)-ish.
remove_once(
    "        self._dynamic_method_matchers: dict[str, tuple[re.Pattern, list[Route]]] = {}\n",
    "dynamic matcher storage",
)
remove_once(
    "                self._rebuild_dynamic_matcher(method)\n",
    "dynamic matcher rebuild call",
)
remove_once(
    "        self._dynamic_method_matchers.clear()\n",
    "dynamic matcher mount clear",
)
text, removed = re.subn(
    r"\n    def _rebuild_dynamic_matcher\(self, method: str\) -> None:\n.*?(?=\n    def enable_css\()",
    "",
    text,
    count=1,
    flags=re.S,
)
if removed == 0 and "def _rebuild_dynamic_matcher" in text:
    raise SystemExit("failed to remove _rebuild_dynamic_matcher")

# 2) Cache parsed template expression ASTs per TemplateEngine.
replace_once(
    "        self._cache: dict[str, tuple[int, int, Template]] = {}\n",
    "        self._cache: dict[str, tuple[int, int, Template]] = {}\n"
    "        self._expression_cache: dict[str, tuple[str, ast.AST, tuple[str, ...]]] = {}\n",
    "_expression_cache:",
)

# 3) Fast path the overwhelmingly common no-filter expression case.
replace_once(
    "    def _split_filters(self, expression: str) -> list[str]:\n"
    "        parts, current = [], []\n",
    "    def _split_filters(self, expression: str) -> list[str]:\n"
    "        if \"|\" not in expression:\n"
    "            expression = expression.strip()\n"
    "            return [expression] if expression else []\n"
    "        parts, current = [], []\n",
    "if \"|\" not in expression:",
)

old_evaluate = '''    def evaluate(self, expression: str, context: t.Mapping[str, t.Any]) -> tuple[str, t.Any]:
        pipeline = self._split_filters(expression)
        if not pipeline:
            return "", ""
        base = pipeline[0]
        value = _TemplateExpression(context).evaluate(base)
        for name in pipeline[1:]:
            fn = self.filters.get(name)
            if fn is None:
                raise TemplateError(f"Unknown template filter: {name}")
            value = fn(value)
        return base, value
'''
new_evaluate = '''    def _compile_expression(self, expression: str) -> tuple[str, ast.AST, tuple[str, ...]]:
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
'''
replace_once(old_evaluate, new_evaluate, "def _compile_expression(")

old_compile = '''    def compile(self, source: str, *, name: str = "<string>") -> Template:
        nodes, _, _ = self._parse_nodes(self._tokenize(source))
        return Template(self, str(source), tuple(nodes), name)
'''
new_compile = '''    def compile(self, source: str, *, name: str = "<string>") -> Template:
        nodes, _, _ = self._parse_nodes(self._tokenize(source))
        frozen_nodes = tuple(nodes)
        self._warm_nodes(frozen_nodes)
        return Template(self, str(source), frozen_nodes, name)
'''
replace_once(old_compile, new_compile, "self._warm_nodes(frozen_nodes)")

night_path.write_text(text, encoding="utf-8")

# Update the internal implementation test: behavior matters, not existence of
# the removed unused combined matcher cache.
test_path = Path("tests/test_fast_paths.py")
test_text = test_path.read_text(encoding="utf-8")
test_text = test_text.replace(
    "def test_combined_dynamic_matcher_selects_route_and_converts_params():\n",
    "def test_multiple_dynamic_routes_select_and_convert_params():\n",
    1,
)
test_text = test_text.replace(
    '    assert "GET" in app._dynamic_method_matchers\n',
    "",
    1,
)
test_path.write_text(test_text, encoding="utf-8")
