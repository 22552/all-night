from pathlib import Path

path = Path('night.py')
text = path.read_text(encoding='utf-8')

old = '''        self.status = int(status)\n        self.body = _to_bytes(body)\n        self.headers = {k.lower(): v for k, v in (headers or {}).items()}\n        self.raw_headers = list(raw_headers or ())\n'''
new = '''        self.status = int(status)\n        self.body = _to_bytes(body)\n        self.headers = {k.lower(): v for k, v in headers.items()} if headers else {}\n        self.raw_headers = list(raw_headers) if raw_headers else []\n'''
assert old in text, 'Response init anchor missing'
text = text.replace(old, new, 1)

old = '''    def asgi_headers(self) -> list[tuple[bytes, bytes]]:\n        normal = [(k, v) for k, v in self.headers.items() if k != "set-cookie"]\n        return [(k.encode("latin-1"), v.encode("latin-1")) for k, v in normal + self.raw_headers]\n'''
new = '''    def asgi_headers(self) -> list[tuple[bytes, bytes]]:\n        encoded = [\n            (k.encode("latin-1"), v.encode("latin-1"))\n            for k, v in self.headers.items()\n            if k != "set-cookie"\n        ]\n        if self.raw_headers:\n            encoded.extend(\n                (k.encode("latin-1"), v.encode("latin-1"))\n                for k, v in self.raw_headers\n            )\n        return encoded\n'''
assert old in text, 'asgi_headers anchor missing'
text = text.replace(old, new, 1)

old = '''        body = encoded if isinstance(encoded, bytes) else str(encoded).encode("utf-8")\n        h = dict(headers or {})\n        h.setdefault("content-type", "application/json; charset=utf-8")\n        super().__init__(body=body, status=status, headers=h)\n'''
new = '''        body = encoded if isinstance(encoded, bytes) else str(encoded).encode("utf-8")\n        if headers:\n            h = dict(headers)\n            h.setdefault("content-type", "application/json; charset=utf-8")\n            super().__init__(body=body, status=status, headers=h)\n        else:\n            super().__init__(\n                body=body,\n                status=status,\n                content_type="application/json; charset=utf-8",\n            )\n'''
assert old in text, 'JSONResponse anchor missing'
text = text.replace(old, new, 1)

old = '''class PlainTextResponse(Response):\n    def __init__(self, text: str, status: int = 200, headers: t.Mapping[str, str] | None = None):\n        h = dict(headers or {})\n        h.setdefault("content-type", "text/plain; charset=utf-8")\n        super().__init__(body=text, status=status, headers=h)\n\n\nclass HTMLResponse(Response):\n    def __init__(self, html: str, status: int = 200, headers: t.Mapping[str, str] | None = None):\n        h = dict(headers or {})\n        h.setdefault("content-type", "text/html; charset=utf-8")\n        super().__init__(body=html, status=status, headers=h)\n'''
new = '''class PlainTextResponse(Response):\n    def __init__(self, text: str, status: int = 200, headers: t.Mapping[str, str] | None = None):\n        if headers:\n            h = dict(headers)\n            h.setdefault("content-type", "text/plain; charset=utf-8")\n            super().__init__(body=text, status=status, headers=h)\n        else:\n            super().__init__(body=text, status=status, content_type="text/plain; charset=utf-8")\n\n\nclass HTMLResponse(Response):\n    def __init__(self, html: str, status: int = 200, headers: t.Mapping[str, str] | None = None):\n        if headers:\n            h = dict(headers)\n            h.setdefault("content-type", "text/html; charset=utf-8")\n            super().__init__(body=html, status=status, headers=h)\n        else:\n            super().__init__(body=html, status=status, content_type="text/html; charset=utf-8")\n'''
assert old in text, 'text/html response anchor missing'
text = text.replace(old, new, 1)

path.write_text(text, encoding='utf-8')
