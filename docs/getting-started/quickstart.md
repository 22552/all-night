# Quickstart

Night **0.1.4** requires Python **3.11+**. The PyPI package is `all-night`; applications import `night`.

## Install

```bash
python -m pip install -U all-night
```

For the built-in `night run` command, install an ASGI server too:

```bash
python -m pip install -U uvicorn
```

Create `app.py`:

```python
from night import Night

app = Night()

@app.get("/")
def index():
    return {"message": "Hello, Night"}

@app.get("/users/<int:user_id>")
def get_user(user_id: int):
    return {"id": user_id}
```

## Run

Use Night's CLI:

```bash
night run app.py
```

The CLI defaults to `127.0.0.1:8000` and also accepts an explicit host and port:

```bash
night run app.py --host 0.0.0.0 --port 8080
```

Or run Night with any ASGI server:

```bash
uvicorn app:app --reload
```

Night itself does not require Uvicorn for normal CPython use; Uvicorn is only needed when you choose it as the server or use the current `night run` implementation.

> **CLI note:** In 0.1.4, `night routes` and `night shell` do not take an application path argument. The older examples `night routes app.py` and `night shell app.py` were incorrect and have been removed from this quickstart. See [Tooling and CLI](../reference/tooling.md) for the current behavior and limitations.

## Add routes

Night supports both decorator registration and fluent registration.

```python
@app.post("/echo")
async def echo(req):
    return {"received": await req.json()}

app.get("/health", lambda: {"ok": True})
```

Common dynamic converters include typed integer parameters:

```python
@app.get("/posts/<int:post_id>")
def post(post_id: int):
    return {"post_id": post_id}
```

## Request data

```python
@app.post("/inspect")
async def inspect(req):
    return {
        "method": req.method,
        "path": req.path,
        "query": req.query,
        "json": await req.json(),
    }
```

Night also supports forms, multipart uploads, cookies, sessions, typed body validation, streaming responses, static files, SSE, and WebSocket routes. See the [HTTP guide](../guides/http.md) and [Realtime guide](../guides/realtime.md).

## Sessions

Pass a `secret_key` only when you need signed sessions, flash messages, or CSRF helpers:

```python
import os
from night import Night

app = Night(secret_key=os.environ["NIGHT_SECRET_KEY"])
```

Do not hard-code production secrets.

## Test without a server

```python
with app.test_client() as client:
    response = client.get("/users/42")
    assert response.status_code == 200
    assert response.get_json() == {"id": 42}
```

`TestClient` runs the ASGI application in-process and reuses an `asyncio.Runner` between requests. Treat cross-framework TestClient benchmarks as development measurements, not production HTTP throughput claims.

## Where Night can run

The same application model can be hosted in several environments:

- **Normal ASGI / CPython** — Uvicorn, Hypercorn, or another ASGI server
- **Vercel Functions** — direct ASGI application
- **Cloudflare Python Workers** — `cloudflare_fetch()` bridge
- **Node.js 22 / 24** — Pyodide + `night_node.mjs`
- **Netlify Functions** — Node adapter and Web-standard Request/Response
- **Browser Night** — Pyodide inside the browser tab

See [Deployment](../operations/deployment.md) for the platform map.

## Next

- [Documentation index](../README.md)
- [HTTP applications](../guides/http.md)
- [Templates](../guides/templates.md)
- [Realtime: SSE and WebSocket](../guides/realtime.md)
- [Tooling and CLI](../reference/tooling.md)
- [Deployment](../operations/deployment.md)
- [Browser Night](../guides/browser.md)
- [Cloudflare Python Workers](../guides/cloudflare-workers.md)
