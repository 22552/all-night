import asyncio

from night import Night, Request


def test_compiled_route_invokers_cover_hot_call_shapes():
    app = Night()

    @app.get('/static')
    def static():
        return 'ok'

    @app.get('/users/<int:id>')
    def user(id: int):
        return {'id': id}

    @app.get('/request')
    def request_positional(request: Request):
        return request.path

    @app.get('/keyword')
    def request_keyword(*, req: Request):
        return req.path

    @app.get('/async/<int:id>')
    async def async_user(id: int):
        await asyncio.sleep(0)
        return {'id': id}

    client = app.test_client()
    try:
        assert client.get('/static').text == 'ok'
        assert client.get('/users/42').json() == {'id': 42}
        assert client.get('/request').text == '/request'
        assert client.get('/keyword').text == '/keyword'
        assert client.get('/async/7').json() == {'id': 7}

        for route in app.routes:
            assert callable(route._night_invoke)
    finally:
        client.close()


def test_hooks_still_run_with_invoke_fast_path():
    app = Night()
    seen = []

    @app.before_request
    def before(req):
        seen.append(('before', req.path))

    @app.after_request
    def after(req, resp):
        seen.append(('after', req.path))
        return resp

    @app.get('/')
    def index():
        return 'ok'

    client = app.test_client()
    try:
        assert client.get('/').text == 'ok'
    finally:
        client.close()
    assert seen == [('before', '/'), ('after', '/')]
