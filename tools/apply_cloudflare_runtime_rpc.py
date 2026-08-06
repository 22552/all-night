from pathlib import Path

night_path = Path('night.py')
s = night_path.read_text()

anchor = '''    def openapi(self) -> dict[str, t.Any]:\n'''
if anchor not in s:
    raise SystemExit('Night openapi anchor not found')

methods = r'''    async def cloudflare_rpc(
        self,
        method: str,
        args: t.Any = None,
        kwargs: t.Any = None,
    ) -> t.Any:
        """Invoke a registered ``@app.rpc`` method over Workers RPC.

        The Cloudflare runtime SDK owns the Python <-> JavaScript/RPC value
        conversion. Keeping this bridge lazy preserves Night's zero-dependency
        behavior outside Cloudflare Workers.
        """
        try:
            from workers.rpc import python_from_rpc, python_to_rpc
        except ImportError as exc:
            raise RuntimeError(
                "Cloudflare RPC requires workers-runtime-sdk inside a Python Worker"
            ) from exc

        fn = self.rpc_methods.get(str(method))
        if fn is None:
            raise KeyError(f"Unknown Night RPC method: {method}")

        call_args = python_from_rpc(args) if args is not None else []
        call_kwargs = python_from_rpc(kwargs) if kwargs is not None else {}
        if not isinstance(call_args, (list, tuple)):
            raise TypeError("Workers RPC args must be a list or tuple")
        if not isinstance(call_kwargs, dict):
            raise TypeError("Workers RPC kwargs must be a mapping")

        result = fn(*call_args, **call_kwargs)
        if inspect.isawaitable(result):
            result = await t.cast(t.Awaitable, result)
        return python_to_rpc(result)

    async def cloudflare_fetch(self, request: t.Any, *, response_class: t.Any = None) -> t.Any:
        """Serve a Cloudflare Workers Request through Night's ASGI core.

        This embeds the old portable/web adapter path into Night itself. It
        accepts the official ``workers.Request`` wrapper and also keeps a
        fallback for raw JS Request objects used by older compatibility dates.
        """
        try:
            if response_class is None:
                from workers import Response as response_class
        except ImportError as exc:
            raise RuntimeError(
                "Cloudflare fetch integration requires workers-runtime-sdk"
            ) from exc

        parsed = urllib.parse.urlsplit(str(request.url))
        method_value = getattr(request.method, "value", request.method)
        method = str(method_value).upper()

        header_source = getattr(request, "headers", ())
        try:
            header_items = header_source.items()
        except Exception:
            try:
                header_items = dict(header_source).items()
            except Exception:
                header_items = ()
        headers = [
            (str(key).lower().encode("latin-1"), str(value).encode("latin-1"))
            for key, value in header_items
        ]

        body = b""
        if method not in {"GET", "HEAD"}:
            if hasattr(request, "bytes"):
                body = bytes(await request.bytes())
            else:
                raw = await request.arrayBuffer()
                try:
                    body = bytes(raw.to_py())
                except Exception:
                    body = bytes(raw)
            if len(body) > self.max_body_size:
                raise HTTPError(413, "Request body too large")

        encoded_path = parsed.path or "/"
        decoded_path = urllib.parse.unquote(encoded_path)
        scheme = parsed.scheme or "https"
        port = parsed.port or (443 if scheme == "https" else 80)
        scope = {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "scheme": scheme,
            "path": decoded_path,
            "raw_path": encoded_path.encode("utf-8"),
            "query_string": parsed.query.encode("latin-1"),
            "headers": headers,
            "server": (parsed.hostname or "edge", port),
            "client": None,
        }

        received = False
        async def receive():
            nonlocal received
            if received:
                return {"type": "http.request", "body": b"", "more_body": False}
            received = True
            return {"type": "http.request", "body": body, "more_body": False}

        events: list[dict[str, t.Any]] = []
        async def send(event):
            events.append(event)

        await self(scope, receive, send)
        start = next((event for event in events if event.get("type") == "http.response.start"), None)
        if start is None:
            raise RuntimeError("Night produced no HTTP response start event")
        chunks = [
            event.get("body", b"")
            for event in events
            if event.get("type") == "http.response.body"
        ]
        web_headers = [
            (key.decode("latin-1"), value.decode("latin-1"))
            for key, value in start.get("headers", ())
        ]
        return response_class(
            b"".join(chunks),
            status=int(start["status"]),
            headers=web_headers,
        )

'''

s = s.replace(anchor, methods + anchor, 1)
night_path.write_text(s)

entry = Path('deploy/cloudflare-night/src/entry.py')
es = entry.read_text()
es = es.replace('from web_runtime import CloudflareWorkerMixin\n', '')
es = es.replace('from workers import Response, WorkerEntrypoint\n', 'from workers import WorkerEntrypoint\n')

rpc_anchor = '''@app.delete("/api/todos/<id>")\nasync def delete_todo(id: str):\n    todo = await _get_todo(id)\n    if todo is None:\n        return {"error": "todo not found"}\n    await _kv.delete(_todo_key(id))\n    return todo\n\n\n'''
rpc_block = rpc_anchor + '''@app.rpc("todo_count")\nasync def todo_count():\n    result = await _kv.list(prefix="todo:")\n    keys = result.get("keys", [])\n    return len(keys)\n\n\n'''
if rpc_anchor not in es:
    raise SystemExit('entry rpc anchor not found')
es = es.replace(rpc_anchor, rpc_block, 1)

old_class = '''class Default(CloudflareWorkerMixin, WorkerEntrypoint):\n    app = app\n    web_response_class = Response\n\n    async def fetch(self, request):\n        global _kv\n        _kv = self.env.TODOS\n        return await CloudflareWorkerMixin.fetch(self, request)\n'''
new_class = '''class Default(WorkerEntrypoint):\n    async def fetch(self, request):\n        global _kv\n        _kv = self.env.TODOS\n        return await app.cloudflare_fetch(request)\n\n    async def night_rpc(self, method, args=None, kwargs=None):\n        global _kv\n        _kv = self.env.TODOS\n        return await app.cloudflare_rpc(method, args, kwargs)\n'''
if old_class not in es:
    raise SystemExit('old Cloudflare worker class not found')
es = es.replace(old_class, new_class, 1)
entry.write_text(es)

package = Path('deploy/cloudflare-night/package.json')
ps = package.read_text()
old_build = '"build": "curl -fsSL https://raw.githubusercontent.com/22552/all-night/9a241910b8f888a67720c8b80bde1b139604faff/night.py -o src/night.py && cp portable_runtime.py src/portable_runtime.py && cp web_runtime.py src/web_runtime.py"'
new_build = '"build": "if [ -f ../../night.py ]; then cp ../../night.py src/night.py; else curl -fsSL https://raw.githubusercontent.com/22552/all-night/main/night.py -o src/night.py; fi"'
if old_build not in ps:
    raise SystemExit('package build anchor not found')
package.write_text(ps.replace(old_build, new_build, 1))

readme = Path('deploy/cloudflare-night/README.md')
rs = readme.read_text()
rs = rs.replace(
    '- Night, the portable runtime adapter, and the Web runtime adapter are vendored into `src/` during the build.\n',
    '- Night embeds the Cloudflare Request/Response bridge directly; the template vendors only `night.py` into `src/`.\n- `workers-runtime-sdk` provides the official Python/JavaScript Workers RPC conversion layer. The demo exposes the same `@app.rpc("todo_count")` method over HTTP JSON-RPC and the `night_rpc()` WorkerEntrypoint method for Service Bindings.\n',
)
rs = rs.replace(
    '- Streaming/SSE and WebSockets are not part of this first portable Web adapter demo.\n',
    '- The embedded bridge currently buffers streaming response chunks before constructing the Workers `Response`; native streaming remains a future optimization.\n',
)
readme.write_text(rs)

for stale in (
    Path('deploy/cloudflare-night/portable_runtime.py'),
    Path('deploy/cloudflare-night/web_runtime.py'),
):
    if stale.exists():
        stale.unlink()
