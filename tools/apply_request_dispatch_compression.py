from pathlib import Path

p = Path('night.py')
s = p.read_text()

s = s.replace(
'''    async def _dispatch(self, req: Request) -> Response:\n''',
'''    async def _dispatch(self, req: Request, path: str | None = None, method: str | None = None) -> Response:\n        path = req.path if path is None else path\n        method = req.method if method is None else method\n''', 1)
s = s.replace(
'''        direct = self._match_direct_for_dispatch(req.path, req.method)\n''',
'''        direct = self._match_direct_for_dispatch(path, method)\n''', 1)
s = s.replace(
'''            route, params = self._match_method(req.path, req.method)\n''',
'''            route, params = self._match_method(path, method)\n''', 1)

old = '''        req = Request(scope=request_scope, receive=receive, send=send, max_body_size=self.max_body_size)\n        token = _current_request.set(req)\n        try:\n\n            async def call_next(i: int = 0) -> Response:\n                if i >= len(self.middlewares):\n                    return await self._dispatch(req)\n\n                mw = self.middlewares[i]\n\n                async def nxt() -> Response:\n                    return await call_next(i + 1)\n\n                return await mw(req, nxt)\n\n            # Automatic OPTIONS and HEAD support.\n            if req.method == "OPTIONS":\n                allowed = self._allowed_methods_for_path(req.path)\n'''
new = '''        req = Request(scope=request_scope, receive=receive, send=send, max_body_size=self.max_body_size)\n        method = (request_scope.get("method") or "GET").upper()\n        path = request_scope.get("path") or "/"\n        token = _current_request.set(req)\n        try:\n            # Automatic OPTIONS and HEAD support.\n            if method == "OPTIONS":\n                allowed = self._allowed_methods_for_path(path)\n'''
if old not in s:
    raise SystemExit('call_next block anchor missing')
s = s.replace(old, new, 1)
s = s.replace(
'''            is_head = req.method == "HEAD"\n''',
'''            is_head = method == "HEAD"\n''', 1)
s = s.replace(
'''                req.scope["method"] = "GET"\n\n            try:\n                if self.middlewares:\n                    resp = await call_next(0)\n                else:\n                    resp = await self._dispatch(req)\n''',
'''                req.scope["method"] = "GET"\n                method = "GET"\n\n            try:\n                if self.middlewares:\n                    async def call_next(i: int = 0) -> Response:\n                        if i >= len(self.middlewares):\n                            return await self._dispatch(req, path, method)\n\n                        mw = self.middlewares[i]\n\n                        async def nxt() -> Response:\n                            return await call_next(i + 1)\n\n                        return await mw(req, nxt)\n\n                    resp = await call_next(0)\n                else:\n                    resp = await self._dispatch(req, path, method)\n''', 1)

p.write_text(s)
