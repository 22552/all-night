from pathlib import Path
import re

ROOT = Path(__file__).parent.parent
BROWSER = ROOT / "deploy" / "browser-night"


def test_pyodide_service_worker_is_versioned_and_cache_first():
    worker = (BROWSER / "sw.js").read_text()
    assert "night-pyodide-v1" in worker
    assert "cdn.jsdelivr.net" in worker
    assert "/pyodide" in worker
    assert "cache.match(event.request)" in worker
    assert "cache.put(event.request, response.clone())" in worker
    assert "clients.claim" in worker


def test_browser_shells_register_pyodide_cache():
    for name in ("404.html", "debug.html"):
        html = (BROWSER / name).read_text()
        assert "serviceWorker.register" in html
        assert "sw.js" in html
        assert "enablePyodideCache" in html


def test_pages_builds_root_index_and_keeps_404_fallback():
    workflow = (ROOT / ".github" / "workflows" / "pages-browser-night.yml").read_text()
    assert "cp -R deploy/browser-night/. _site/" in workflow
    assert "cp deploy/browser-night/404.html _site/index.html" in workflow
    assert (BROWSER / "404.html").exists()


def test_release_version_matches_pyproject():
    version = (ROOT / ".release" / "version").read_text().strip()
    pyproject = (ROOT / "pyproject.toml").read_text()
    assert f'version = "{version}"' in pyproject


def test_midnight_is_not_packaged_in_all_night_core():
    pyproject = (ROOT / "pyproject.toml").read_text()
    setuptools = pyproject.split("[tool.setuptools]", 1)[1]
    assert '"night_midnight"' not in setuptools
    assert '"night_midnight_scope"' not in setuptools
    assert '"midnight.js"' not in setuptools


def test_midnight_distribution_owns_midnight_runtime():
    core_version = (ROOT / ".release" / "version").read_text().strip()
    pyproject = (ROOT / "packages" / "midnight" / "pyproject.toml").read_text()
    assert 'name = "all-night-midnight"' in pyproject
    match = re.search(r'^version = "([^"]+)"$', pyproject, re.MULTILINE)
    assert match is not None
    assert match.group(1)
    assert f'dependencies = ["all-night=={core_version}"]' in pyproject
    assert '"night_midnight"' in pyproject
    assert '"night_midnight_scope"' in pyproject
    assert '"../../midnight.js"' in pyproject


def test_publish_builds_core_and_midnight_distributions():
    workflow = (ROOT / ".github" / "workflows" / "publish.yml").read_text()
    assert "python -m build --outdir dist ." in workflow
    assert "python -m build --wheel --outdir dist packages/midnight" in workflow


def test_midnight_can_publish_independently():
    workflow = (ROOT / ".github" / "workflows" / "publish-midnight.yml").read_text()
    assert '"midnight-v*"' in workflow
    assert "python -m build --wheel --outdir dist packages/midnight" in workflow
    assert "python -m build --outdir dist ." not in workflow
    assert "https://pypi.org/p/all-night-midnight" in workflow
