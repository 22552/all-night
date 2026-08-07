import importlib.util
import pathlib
import tomllib


ROOT = pathlib.Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "deploy" / "vercel-night"


def test_vercel_template_declares_asgi_entrypoint():
    config = tomllib.loads((TEMPLATE / "pyproject.toml").read_text())
    assert config["tool"]["vercel"]["entrypoint"] == "app.py"
    assert "all-night>=0.1.1" in config["project"]["dependencies"]
    assert config["project"]["requires-python"] == ">=3.12"


def test_vercel_template_exports_night_asgi_app():
    spec = importlib.util.spec_from_file_location("night_vercel_example", TEMPLATE / "app.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    from night import Night

    assert isinstance(module.app, Night)
    with module.app.test_client() as client:
        assert client.get("/health").get_json() == {"ok": True}
        assert client.get("/users/42").get_json() == {"id": 42}
