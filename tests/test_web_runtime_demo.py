import asyncio
import importlib.util
from pathlib import Path


def load_demo():
    path = Path(__file__).parent.parent / "examples" / "web_runtime_demo.py"
    spec = importlib.util.spec_from_file_location("web_runtime_demo", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_demo_hello():
    demo = load_demo()
    response = asyncio.run(
        demo.fetch(
            demo.app,
            demo.DemoRequest("https://example.test/hello"),
            response_class=demo.DemoResponse,
        )
    )
    assert response.status == 200
    assert response.body == b'{"message":"Night on a Web-style runtime"}'


def test_demo_echo():
    demo = load_demo()
    response = asyncio.run(
        demo.fetch(
            demo.app,
            demo.DemoRequest(
                "https://example.test/echo",
                method="POST",
                headers=[("content-type", "application/json")],
                body=b'{"edge":true}',
            ),
            response_class=demo.DemoResponse,
        )
    )
    assert response.status == 200
    assert response.body == b'{"echo":{"edge":true}}'
