# Quickstart

Create `app.py` next to `night.py` (or install/copy the module into your project).

```python
from night import Night

app = Night(secret_key="replace-with-a-random-secret")

@app.get("/")
def index():
    return {"message": "Hello, Night"}
```

Run it with an ASGI server:

```bash
uvicorn app:app --reload
```

Night also includes a small CLI:

```bash
python night.py run app.py
python night.py routes
python night.py shell
```

`secret_key` is only needed when using signed sessions, flash messages, or CSRF helpers. Keep it in an environment variable in deployed applications.

## A JSON endpoint

```python
@app.post("/echo")
async def echo(req):
    return {"received": await req.json()}
```

See [HTTP applications](../guides/http.md) for validation and uploads.


