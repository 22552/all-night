# Byakuya

**Byakuya** is the tiny, dependency-free HTTP/ASGI core extracted from Night.

It keeps the part needed to build small Night-style HTTP applications while leaving the full framework features in `all-night`.

## Install

```bash
pip install byakuya
```

For a production ASGI server:

```bash
pip install "byakuya[standard]"
```

## Use

The distribution is named **Byakuya**, but the Python module is intentionally named **`tnight`**.

```python
from tnight import Night

app = Night()

@app.get("/")
def index():
    return {"hello": "byakuya"}

@app.get("/users/<int:user_id>")
def user(user_id):
    return {"id": user_id}
```

Run it with an ASGI server such as Uvicorn:

```bash
uvicorn app:app
```

## Included

- dependency-free Python core
- ASGI HTTP application callable
- `GET`, `POST`, `PUT`, `PATCH`, `DELETE`
- automatic `HEAD` handling
- `OPTIONS` and `405 Allow`
- static routes
- `<name>`, `<str:name>`, and `<int:name>` path parameters
- query parsing
- request body access and JSON decoding
- `Response`, `PlainTextResponse`, `HTMLResponse`, `JSONResponse`
- automatic response coercion for strings, bytes, dicts, lists, tuples, and `None`
- configurable request-body size limit

## Deliberately excluded

Byakuya is not the full Night distribution. It does not package Midnight, ORM, MCP, Cloudflare adapters, DevTools, NightCLI/rooms, template engine, WebSocket helpers, SSE helpers, deployment adapters, or the rest of the full Night stack.

Use [`all-night`](https://github.com/22552/all-night) when those features are needed.

## Naming

- project/distribution: **Byakuya** / `byakuya`
- import: **`tnight`**
- development branch: **`night/tiny`**

Byakuya remains part of the Night project and is intended as its smallest standalone runtime.
