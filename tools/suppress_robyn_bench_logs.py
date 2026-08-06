from pathlib import Path

p = Path('benchmarks/fast_path.py')
s = p.read_text()
if 'import logging\n' not in s:
    s = s.replace('import asyncio\n', 'import asyncio\nimport logging\n', 1)
old = '''def build_robyn(*, many_dynamic: bool):\n    from robyn import Robyn\n    from robyn.testing import TestClient\n\n    app = Robyn(__file__)\n'''
new = '''def build_robyn(*, many_dynamic: bool):\n    from robyn import Robyn\n    from robyn.testing import TestClient\n\n    logging.getLogger("robyn.logger").setLevel(logging.CRITICAL)\n    app = Robyn(__file__)\n'''
if old in s:
    s = s.replace(old, new, 1)
elif 'logging.getLogger("robyn.logger").setLevel(logging.CRITICAL)' not in s:
    raise SystemExit('Robyn benchmark anchor missing')
p.write_text(s)
