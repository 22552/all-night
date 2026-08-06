from pathlib import Path

p = Path('night.py')
s = p.read_text()

# 1) second-granularity Date cache
s = s.replace('import tempfile\nimport traceback\n', 'import tempfile\nimport traceback\nimport time\n', 1)
anchor = '''def _http_date(dt: _dt.datetime | None = None) -> str:\n    if dt is None:\n        dt = _dt.datetime.now(tz=_dt.timezone.utc)\n    if dt.tzinfo is None:\n        dt = dt.replace(tzinfo=_dt.timezone.utc)\n    return email.utils.format_datetime(dt, usegmt=True)\n\n'''
cache = anchor + '''_HTTP_DATE_CACHE_SECOND = -1\n_HTTP_DATE_CACHE_VALUE = ""\n\ndef _cached_http_date() -> str:\n    global _HTTP_DATE_CACHE_SECOND, _HTTP_DATE_CACHE_VALUE\n    second = int(time.time())\n    if second != _HTTP_DATE_CACHE_SECOND:\n        _HTTP_DATE_CACHE_SECOND = second\n        _HTTP_DATE_CACHE_VALUE = email.utils.formatdate(second, usegmt=True)\n    return _HTTP_DATE_CACHE_VALUE\n\n'''
if anchor not in s: raise SystemExit('http date anchor missing')
s = s.replace(anchor, cache, 1)
s = s.replace('self.headers["date"] = _http_date()', 'self.headers["date"] = _cached_http_date()')

# 2) per-header lazy scan + tiny cache, preserving full headers property
field = '    _headers: dict[str, str] | None = dataclasses.field(default=None, init=False)\n'
if field not in s: raise SystemExit('headers field missing')
s = s.replace(field, field + '    _header_cache: dict[str, str | None] = dataclasses.field(default_factory=dict, init=False)\n', 1)
old = '''    def header(self, name: str, default: str | None = None) -> str | None:\n        return self.headers.get(name.lower(), default)\n'''
new = '''    def header(self, name: str, default: str | None = None) -> str | None:\n        key = name.lower()\n        if self._headers is not None:\n            return self._headers.get(key, default)\n        if key in self._header_cache:\n            value = self._header_cache[key]\n            return default if value is None else value\n\n        target = key.encode("latin-1")\n        value = None\n        headers = self.scope.get("headers") or ()\n        # Search from the end to preserve the previous "last value wins"\n        # behavior without decoding unrelated headers. ASGI headers are a list.\n        for raw_name, raw_value in reversed(headers):\n            if raw_name == target or raw_name.lower() == target:\n                value = raw_value.decode("latin-1")\n                break\n        self._header_cache[key] = value\n        return default if value is None else value\n'''
if old not in s: raise SystemExit('header method missing')
s = s.replace(old, new, 1)

# 5) make advertised orjson-style bytes serializers actually work
old = '''        body = dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")\n        h = dict(headers or {})\n'''
new = '''        if dumps is json.dumps:\n            encoded = dumps(data, ensure_ascii=False, separators=(",", ":"))\n        else:\n            # Fast serializers such as orjson return bytes and generally do\n            # not accept json.dumps keyword arguments.\n            encoded = dumps(data)\n        body = encoded if isinstance(encoded, bytes) else str(encoded).encode("utf-8")\n        h = dict(headers or {})\n'''
if old not in s: raise SystemExit('JSONResponse anchor missing')
s = s.replace(old, new, 1)

# 6) reuse Route.__post_init__ signature instead of inspecting twice
old = '''def _compile_endpoint(fn: t.Callable) -> _EndpointPlan:\n    try:\n        signature = inspect.signature(fn)\n    except (TypeError, ValueError):\n        signature = None\n'''
new = '''def _compile_endpoint(fn: t.Callable) -> _EndpointPlan:\n    signature = getattr(fn, "__night_signature__", None)\n    if signature is None:\n        try:\n            signature = inspect.signature(fn)\n        except (TypeError, ValueError):\n            signature = None\n'''
if old not in s: raise SystemExit('compile endpoint anchor missing')
s = s.replace(old, new, 1)

# 7) keep method->path index, but avoid allocating {} on every lookup
old = '''        route = self._static_method_index.get(method, {}).get(key)\n        if route is not None:\n            return route, {}\n'''
new = '''        method_routes = self._static_method_index.get(method)\n        if method_routes is not None:\n            route = method_routes.get(key)\n            if route is not None:\n                return route, {}\n'''
if old not in s: raise SystemExit('static lookup anchor missing')
s = s.replace(old, new, 1)

p.write_text(s)
