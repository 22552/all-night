from pathlib import Path

p = Path('night.py')
text = p.read_text(encoding='utf-8')
old = '''    def _coerce_response(self, value: t.Any) -> Response:\n        if isinstance(value, FileHandler):\n            return value.response(request())\n        kind = type(value)\n        if kind is dict or kind is list:\n            return JSONResponse(value, dumps=self._json_dumps)\n        if kind is str:\n            return PlainTextResponse(value)\n        if kind is bytes:\n            return Response(value)\n        if value is None:\n            return Response(b"", status=204)\n'''
new = '''    def _coerce_response(self, value: t.Any) -> Response:\n        kind = type(value)\n        if kind is dict or kind is list:\n            return JSONResponse(value, dumps=self._json_dumps)\n        if kind is str:\n            return PlainTextResponse(value)\n        if kind is bytes:\n            return Response(value)\n        if value is None:\n            return Response(b"", status=204)\n        if isinstance(value, FileHandler):\n            return value.response(request())\n'''
if old not in text:
    raise SystemExit('coerce anchor not found')
p.write_text(text.replace(old, new, 1), encoding='utf-8')
