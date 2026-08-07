from pathlib import Path

path = Path("night.py")
text = path.read_text()
old = '''class TestClient:
    def __init__(self, app: "Night"):
        self.app, self.cookies = app, {}

    def request(self, method: str, path: str, *, data: bytes | str | None = None, headers: dict[str, str] | None = None):
        async def run():
            sent = []
            body = data.encode() if isinstance(data, str) else (data or b"")
            parsed = urllib.parse.urlsplit(path)
            hs = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
            if self.cookies:
                hs.append((b"cookie", "; ".join(f"{k}={v}" for k, v in self.cookies.items()).encode()))
            if body and not any(k == b"content-length" for k, _ in hs): hs.append((b"content-length", str(len(body)).encode()))
            events = [{"type": "http.request", "body": body, "more_body": False}]
            async def receive(): return events.pop(0) if events else {"type": "http.disconnect"}
            async def send(event): sent.append(event)
            scope = {"type": "http", "method": method.upper(), "path": parsed.path or "/", "query_string": parsed.query.encode(), "headers": hs}
            await self.app(scope, receive, send)
            start = next(e for e in sent if e["type"] == "http.response.start")
            for key, value in start["headers"]:
                if key.lower() == b"set-cookie":
                    pair = value.decode().split(";", 1)[0]
                    name, _, cookie_value = pair.partition("=")
                    if name: self.cookies[name] = cookie_value
            chunks = [e.get("body", b"") for e in sent if e["type"] == "http.response.body"]
            return TestResponse(start["status"], {k.decode(): v.decode() for k, v in start["headers"]}, b"".join(chunks))
        return asyncio.run(run())

    def get(self, path, **kwargs): return self.request("GET", path, **kwargs)
    def post(self, path, **kwargs): return self.request("POST", path, **kwargs)
    def query(self, path, **kwargs): return self.request("QUERY", path, **kwargs)
'''
new = '''class TestClient:
    def __init__(self, app: "Night"):
        self.app, self.cookies = app, {}
        self._runner: asyncio.Runner | None = None

    def _run(self, coro):
        if self._runner is None:
            self._runner = asyncio.Runner()
        return self._runner.run(coro)

    def close(self):
        runner, self._runner = self._runner, None
        if runner is not None:
            runner.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def request(self, method: str, path: str, *, data: bytes | str | None = None, headers: dict[str, str] | None = None):
        async def run():
            sent = []
            body = data.encode() if isinstance(data, str) else (data or b"")
            parsed = urllib.parse.urlsplit(path)
            hs = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
            if self.cookies:
                hs.append((b"cookie", "; ".join(f"{k}={v}" for k, v in self.cookies.items()).encode()))
            if body and not any(k == b"content-length" for k, _ in hs): hs.append((b"content-length", str(len(body)).encode()))
            events = [{"type": "http.request", "body": body, "more_body": False}]
            async def receive(): return events.pop(0) if events else {"type": "http.disconnect"}
            async def send(event): sent.append(event)
            scope = {"type": "http", "method": method.upper(), "path": parsed.path or "/", "query_string": parsed.query.encode(), "headers": hs}
            await self.app(scope, receive, send)
            start = next(e for e in sent if e["type"] == "http.response.start")
            for key, value in start["headers"]:
                if key.lower() == b"set-cookie":
                    pair = value.decode().split(";", 1)[0]
                    name, _, cookie_value = pair.partition("=")
                    if name: self.cookies[name] = cookie_value
            chunks = [e.get("body", b"") for e in sent if e["type"] == "http.response.body"]
            return TestResponse(start["status"], {k.decode(): v.decode() for k, v in start["headers"]}, b"".join(chunks))
        return self._run(run())

    def get(self, path, **kwargs): return self.request("GET", path, **kwargs)
    def post(self, path, **kwargs): return self.request("POST", path, **kwargs)
    def query(self, path, **kwargs): return self.request("QUERY", path, **kwargs)
'''
if old not in text:
    raise SystemExit("TestClient block not found")
path.write_text(text.replace(old, new, 1))
