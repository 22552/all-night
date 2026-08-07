# Quickstart

Night 0.1.1 requires Python 3.11+.

## Install

```bash
python -m pip install -U all-night
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

With Uvicorn:

```bash
python -m pip install uvicorn
uvicorn app:app --reload
```

Or use Night's CLI:

```bash
night run app.py
night routes app.py
night shell app.py
```

The normal Night core does not require Uvicorn; any ASGI server can host the application.

## JSON input

```python
@app.post("/echo")
async def echo(req):
    return {"received": await req.json()}
```

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

## Next

- [HTTP applications](../guides/http.md)
- [Cloudflare Python Workers](../guides/cloudflare-workers.md)
- [Deployment](../operations/deployment.md)
