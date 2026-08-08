from pathlib import Path

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


def test_release_version_is_0_1_4():
    pyproject = (ROOT / "pyproject.toml").read_text()
    assert 'version = "0.1.4"' in pyproject
