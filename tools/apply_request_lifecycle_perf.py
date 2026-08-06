from pathlib import Path

p = Path('night.py')
s = p.read_text()

s = s.replace('@dataclasses.dataclass\nclass Request:', '@dataclasses.dataclass(slots=True)\nclass Request:', 1)

old = '''        request_scope = dict(scope)\n        if self.secret_key:\n            request_scope["session_secret"] = self.secret_key\n        req = Request(scope=request_scope, receive=receive, send=send, max_body_size=self.max_body_size)\n'''
new = '''        if self.secret_key:\n            request_scope = dict(scope)\n            request_scope["session_secret"] = self.secret_key\n        else:\n            request_scope = scope\n        req = Request(scope=request_scope, receive=receive, send=send, max_body_size=self.max_body_size)\n'''
if old not in s:
    raise SystemExit('scope copy anchor missing')
s = s.replace(old, new, 1)

old = '''            try:\n                resp = await call_next(0)\n            except HTTPError as he:\n'''
new = '''            try:\n                if self.middlewares:\n                    resp = await call_next(0)\n                else:\n                    resp = await self._dispatch(req)\n            except HTTPError as he:\n'''
if old not in s:
    raise SystemExit('middleware fast path anchor missing')
s = s.replace(old, new, 1)

p.write_text(s)
