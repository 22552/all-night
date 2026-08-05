import json
import pathlib
import py_compile
import tomllib


ROOT = pathlib.Path(__file__).parent / "deploy" / "cloudflare-night"


def test_cloudflare_deploy_template_config():
    config = json.loads((ROOT / "wrangler.jsonc").read_text())
    assert config["main"] == "src/entry.py"
    assert "python_workers" in config["compatibility_flags"]

    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert project["project"]["requires-python"] == ">=3.13"
    assert project["project"]["dependencies"] == []

    package = json.loads((ROOT / "package.json").read_text())
    build = package["scripts"]["build"]
    assert "raw.githubusercontent.com/22552/all-night" in build
    assert "-o src/night.py" in build
    assert "cp portable_runtime.py src/portable_runtime.py" in build
    assert "cp web_runtime.py src/web_runtime.py" in build
    assert "pywrangler deploy" in package["scripts"]["deploy"]


def test_cloudflare_deploy_template_python_compiles():
    py_compile.compile(str(ROOT / "portable_runtime.py"), doraise=True)
    py_compile.compile(str(ROOT / "web_runtime.py"), doraise=True)
    py_compile.compile(str(ROOT / "src" / "entry.py"), doraise=True)


def test_cloudflare_deploy_button_points_to_template():
    readme = (ROOT / "README.md").read_text()
    assert "https://deploy.workers.cloudflare.com/button" in readme
    assert "https://github.com/22552/all-night/tree/main/deploy/cloudflare-night" in readme
