import json
import pathlib
import py_compile
import tomllib


ROOT = pathlib.Path(__file__).parent.parent / "deploy" / "cloudflare-minimal"


def test_minimal_probe_config():
    config = json.loads((ROOT / "wrangler.jsonc").read_text())
    assert config["main"] == "src/entry.py"
    assert config["compatibility_flags"] == ["python_workers"]

    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert project["project"]["dependencies"] == []
    assert project["project"]["requires-python"] == ">=3.13"
    assert "workers-py" in project["dependency-groups"]["dev"]

    package = json.loads((ROOT / "package.json").read_text())
    assert package["scripts"]["build"] == "python -m pip install uv"
    assert package["scripts"]["deploy"] == "uvx --from workers-py pywrangler deploy"


def test_minimal_probe_compiles():
    py_compile.compile(str(ROOT / "src" / "entry.py"), doraise=True)


def test_minimal_probe_is_night_free_and_has_deploy_button():
    entry = (ROOT / "src" / "entry.py").read_text()
    assert "from night" not in entry
    assert "import night" not in entry

    readme = (ROOT / "README.md").read_text()
    assert "https://deploy.workers.cloudflare.com/button" in readme
    assert "https://github.com/22552/all-night/tree/main/deploy/cloudflare-minimal" in readme
