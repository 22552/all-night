from pathlib import Path

path = Path('tests/test_cloudflare_deploy_template.py')
s = path.read_text()

s = s.replace(
    '    assert "cp portable_runtime.py src/portable_runtime.py" in build\n'
    '    assert "cp web_runtime.py src/web_runtime.py" in build\n',
    '    assert "portable_runtime.py" not in build\n'
    '    assert "web_runtime.py" not in build\n'
    '    assert "../../night.py" in build\n',
)

s = s.replace(
    'def test_cloudflare_deploy_template_python_compiles():\n'
    '    py_compile.compile(str(ROOT / "portable_runtime.py"), doraise=True)\n'
    '    py_compile.compile(str(ROOT / "web_runtime.py"), doraise=True)\n'
    '    py_compile.compile(str(ROOT / "src" / "entry.py"), doraise=True)\n',
    'def test_cloudflare_deploy_template_python_compiles():\n'
    '    assert not (ROOT / "portable_runtime.py").exists()\n'
    '    assert not (ROOT / "web_runtime.py").exists()\n'
    '    py_compile.compile(str(ROOT / "src" / "entry.py"), doraise=True)\n',
)

needle = '    assert "Night + Cloudflare Python Workers + KV" in entry\n'
replacement = (
    needle
    + '    assert \'@app.rpc("todo_count")\' in entry\n'
    + '    assert "async def night_rpc" in entry\n'
    + '    assert "app.cloudflare_fetch(request)" in entry\n'
    + '    assert "app.cloudflare_rpc(method, args, kwargs)" in entry\n'
)
if needle not in s:
    raise SystemExit('todo route test anchor missing')
s = s.replace(needle, replacement, 1)

path.write_text(s)
