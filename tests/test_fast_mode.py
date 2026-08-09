import sys
import types

from night import Night


def test_fast_mode_uses_optional_json_serializer(monkeypatch):
    fake = types.ModuleType("orjson")
    fake.dumps = lambda value: b"{\"fast\":true}"
    monkeypatch.setitem(sys.modules, "orjson", fake)

    app = Night().fast()
    response = app._coerce_response({"ignored": True})

    assert app._fast_mode is True
    assert response.body == b"{\"fast\":true}"


def test_fast_returns_self(monkeypatch):
    fake = types.ModuleType("orjson")
    fake.dumps = lambda value: b"{}"
    monkeypatch.setitem(sys.modules, "orjson", fake)
    app = Night()
    assert app.fast() is app
