from pathlib import Path

path = Path("night_midnight.py")
text = path.read_text(encoding="utf-8")

text = text.replace(
'''        self.templates = MidnightTemplateEngine()\n        self.get_session(self.DEFAULT_SESSION)\n''',
'''        self.templates = MidnightTemplateEngine()\n        self._get_session(self.DEFAULT_SESSION)\n''',
1,
)

text = text.replace(
'''    @property\n    def current_session(self) -> MidnightSession:\n        return self.get_session(self.session_id)\n''',
'''    @property\n    def current_session(self) -> MidnightSession:\n        return self._get_session(self.session_id)\n''',
1,
)

old = '''    def get_session(self, session_id: str | None = None) -> MidnightSession:\n        key = self.session_id if session_id is None else str(session_id)\n        session = self._sessions.get(key)\n        if session is None:\n            session = MidnightSession(key)\n            self._sessions[key] = session\n        return session\n'''
new = '''    def _get_session(self, key: str) -> MidnightSession:\n        session = self._sessions.get(key)\n        if session is None:\n            session = MidnightSession(key)\n            self._sessions[key] = session\n        return session\n\n    def get_session(\n        self, session_id: TrustedSessionId | None = None\n    ) -> MidnightSession:\n        \"\"\"Return the current session or an explicitly trusted session.\"\"\"\n        key = self.session_id if session_id is None else str(session_id)\n        return self._get_session(key)\n'''
if old not in text:
    raise SystemExit("get_session block not found")
text = text.replace(old, new, 1)

text = text.replace(
'''        key = str(session_id)\n        session = self.get_session(key)\n        token = self._session_id.set(key)\n''',
'''        key = str(session_id)\n        session = self._get_session(key)\n        token = self._session_id.set(key)\n''',
1,
)

text = text.replace(
'''        if key == self.DEFAULT_SESSION:\n            self.get_session(self.DEFAULT_SESSION)\n''',
'''        if key == self.DEFAULT_SESSION:\n            self._get_session(self.DEFAULT_SESSION)\n''',
1,
)

path.write_text(text, encoding="utf-8")

# Update tests so cross-session access also crosses the explicit trust boundary.
test = Path("tests/test_midnight.py")
t = test.read_text(encoding="utf-8")
t = t.replace('bridge.get_session("alice")', 'bridge.get_session(alice_id)')
t = t.replace('bridge.get_session("bob")', 'bridge.get_session(bob_id)')
test.write_text(t, encoding="utf-8")
