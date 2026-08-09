import asyncio
import time
import pytest
from night import Night

def test_cache_reuses_completed_json_response_and_clones():
    app = Night()
    calls = []

    @app.get('/cached')
    @app.cache
    def cached():
        calls.append(1)
        return {'value': len(calls)}

    with app.test_client() as client:
        first = client.get('/cached')
        second = client.get('/cached')
    assert first.get_json() == {'value': 1}
    assert second.get_json() == {'value': 1}
    assert len(calls) == 1

def test_cache_head_does_not_destroy_cached_body():
    app = Night()
    calls = 0

    @app.get('/cached')
    @app.cache()
    def cached():
        nonlocal calls
        calls += 1
        return 'hello'

    with app.test_client() as client:
        assert client.get('/cached').text == 'hello'
        assert client.request('HEAD', '/cached').data == b''
        assert client.get('/cached').text == 'hello'
    assert calls == 1

def test_cache_ttl_and_clear():
    app = Night()
    calls = 0

    @app.get('/cached')
    @app.cache(ttl=0.01)
    def cached():
        nonlocal calls
        calls += 1
        return {'n': calls}

    with app.test_client() as client:
        assert client.get('/cached').get_json() == {'n': 1}
        cached.cache_clear()
        assert client.get('/cached').get_json() == {'n': 2}
        time.sleep(0.02)
        assert client.get('/cached').get_json() == {'n': 3}

def test_cache_rejects_request_dependent_endpoint():
    app = Night()
    with pytest.raises(TypeError):
        @app.cache
        def bad(req):
            return req.path
