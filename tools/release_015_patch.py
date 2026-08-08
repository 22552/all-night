from pathlib import Path

path = Path('night.py')
text = path.read_text(encoding='utf-8')

# importlib.util is used by the CLI to select installed fast Uvicorn backends.
if 'import importlib.util\n' not in text:
    text = text.replace('import inspect\n', 'import inspect\nimport importlib.util\n', 1)

# Every Router gets a serializer hook; Night.fast() swaps it to orjson.dumps.
anchor = '    def __init__(self):\n        self.routes: list[Route] = []\n'
replace = '    def __init__(self):\n        self.routes: list[Route] = []\n        self._json_dumps: t.Callable[..., t.Any] = json.dumps\n        self._fast_mode = False\n'
if anchor in text:
    text = text.replace(anchor, replace, 1)
elif 'self._json_dumps' not in text:
    raise SystemExit('Router.__init__ anchor missing')

anchor = '        if kind is dict or kind is list:\n            return JSONResponse(value)\n'
replace = '        if kind is dict or kind is list:\n            return JSONResponse(value, dumps=self._json_dumps)\n'
if anchor in text:
    text = text.replace(anchor, replace, 1)
elif 'JSONResponse(value, dumps=self._json_dumps)' not in text:
    raise SystemExit('_coerce_response anchor missing')

# Insert Night.fast() before the first method following Night.__init__.
if '    def fast(self) -> "Night":\n' not in text:
    lines = text.splitlines(keepends=True)
    class_i = next(i for i, line in enumerate(lines) if line.startswith('class Night(Router):'))
    init_i = next(i for i in range(class_i + 1, len(lines)) if lines[i].startswith('    def __init__('))
    next_method = next(i for i in range(init_i + 1, len(lines)) if (lines[i].startswith('    def ') or lines[i].startswith('    async def ')))
    method = '''    def fast(self) -> "Night":\n        """Enable Night's optional CPython fast profile.\n\n        Requires ``all-night[standard]``. Dict/list responses use ``orjson``;\n        ``night run`` also selects uvloop/httptools/websockets when available.\n        External ASGI servers keep control of their own event loop/backend.\n        """\n        try:\n            import orjson\n        except ImportError as exc:\n            raise RuntimeError(\n                "Night.fast() requires the standard profile: "\n                "pip install 'all-night[standard]'"\n            ) from exc\n        self._json_dumps = orjson.dumps\n        self._fast_mode = True\n        return self\n\n'''
    lines[next_method:next_method] = [method]
    text = ''.join(lines)

anchor = '        import uvicorn\n        uvicorn.run(target, host=args.host, port=args.port)\n'
replace = '''        import uvicorn\n        run_options: dict[str, t.Any] = {}\n        if bool(getattr(target, "_fast_mode", False)):\n            if importlib.util.find_spec("uvloop") is not None:\n                run_options["loop"] = "uvloop"\n            if importlib.util.find_spec("httptools") is not None:\n                run_options["http"] = "httptools"\n            if importlib.util.find_spec("websockets") is not None:\n                run_options["ws"] = "websockets"\n        uvicorn.run(target, host=args.host, port=args.port, **run_options)\n'''
if anchor in text:
    text = text.replace(anchor, replace, 1)
elif 'run_options["loop"] = "uvloop"' not in text:
    raise SystemExit('CLI uvicorn anchor missing')

path.write_text(text, encoding='utf-8')

# Focused fast-mode coverage.
Path('tests/test_fast_mode.py').write_text('''import sys\nimport types\n\nfrom night import Night\n\n\ndef test_fast_mode_uses_optional_json_serializer(monkeypatch):\n    fake = types.ModuleType("orjson")\n    fake.dumps = lambda value: b"{\\\"fast\\\":true}"\n    monkeypatch.setitem(sys.modules, "orjson", fake)\n\n    app = Night().fast()\n    response = app._coerce_response({"ignored": True})\n\n    assert app._fast_mode is True\n    assert response.body == b"{\\\"fast\\\":true}"\n\n\ndef test_fast_returns_self(monkeypatch):\n    fake = types.ModuleType("orjson")\n    fake.dumps = lambda value: b"{}"\n    monkeypatch.setitem(sys.modules, "orjson", fake)\n    app = Night()\n    assert app.fast() is app\n''', encoding='utf-8')
