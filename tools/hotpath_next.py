from pathlib import Path

p = Path('night.py')
text = p.read_text(encoding='utf-8')
old = "    def _match_direct_for_dispatch(self, path: str, method: str):\n        key = path.rstrip('/') or '/'\n"
new = "    def _match_direct_for_dispatch(self, path: str, method: str):\n        key = path if path == '/' or not path.endswith('/') else path.rstrip('/')\n"
if old not in text:
    raise SystemExit('match-direct anchor not found')
p.write_text(text.replace(old, new, 1), encoding='utf-8')
