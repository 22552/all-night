from pathlib import Path

p = Path('night.py')
text = p.read_text(encoding='utf-8')

# 1) Prioritize the common primitive response types before the rare FileHandler isinstance path.
old = '''    def _coerce_response(self, value: t.Any) -> Response:\n        if isinstance(value, FileHandler):\n            return value.response(request())\n        kind = type(value)\n        if kind is dict or kind is list:\n            return JSONResponse(value, dumps=self._json_dumps)\n        if kind is str:\n            return PlainTextResponse(value)\n        if kind is bytes:\n            return Response(value)\n        if value is None:\n            return Response(b"", status=204)\n'''
new = '''    def _coerce_response(self, value: t.Any) -> Response:\n        kind = type(value)\n        if kind is dict or kind is list:\n            return JSONResponse(value, dumps=self._json_dumps)\n        if kind is str:\n            return PlainTextResponse(value)\n        if kind is bytes:\n            return Response(value)\n        if value is None:\n            return Response(b"", status=204)\n        if isinstance(value, FileHandler):\n            return value.response(request())\n'''
if old not in text:
    raise SystemExit('coerce anchor missing')
text = text.replace(old, new, 1)

# 2) Do not allocate a per-request header cache until header() is actually used.
old = "    _header_cache: dict[str, str | None] = dataclasses.field(default_factory=dict, init=False)\n"
new = "    _header_cache: dict[str, str | None] | None = dataclasses.field(default=None, init=False)\n"
if old not in text:
    raise SystemExit('header cache field anchor missing')
text = text.replace(old, new, 1)

old = '''        if key in self._header_cache:\n            value = self._header_cache[key]\n            return default if value is None else value\n\n        target = key.encode("latin-1")\n'''
new = '''        cache = self._header_cache\n        if cache is not None and key in cache:\n            value = cache[key]\n            return default if value is None else value\n\n        target = key.encode("latin-1")\n'''
if old not in text:
    raise SystemExit('header cache read anchor missing')
text = text.replace(old, new, 1)

old = '''        self._header_cache[key] = value\n        return default if value is None else value\n'''
new = '''        if cache is None:\n            cache = {}\n            self._header_cache = cache\n        cache[key] = value\n        return default if value is None else value\n'''
if old not in text:
    raise SystemExit('header cache write anchor missing')
text = text.replace(old, new, 1)

p.write_text(text, encoding='utf-8')
