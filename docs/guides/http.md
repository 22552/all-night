# HTTP applications

## Routes

```python
@app.get("/users/<int:user_id>", name="user")
def get_user(user_id: int):
    return {"id": user_id}

@app.post("/users")
async def create_user(req):
    return await req.json()
```

Available helpers are `get`, `post`, `put`, `patch`, `delete`, `query`, and `purge`. GET routes automatically answer HEAD. OPTIONS is generated with an `Allow` header.

Routes can also be registered explicitly or fluently:

```python
def home():
    return "home"

def login():
    return "login"

app.add_route("GET", "/health", lambda: {"ok": True})
app.get("/", home).post("/login", login)
```

Passing a handler directly returns the router/app, so route helpers can be chained. Calling `app.get("/path")` without a handler keeps the normal decorator form.

Path converters are `str`, `int`, and `path`. Use `app.url_for("user", user_id=42)` to build named URLs.

## Reading input

- `await req.body()`, `await req.text()`, `await req.json()`
- `await req.form()` for URL-encoded and multipart forms
- `await req.files()` for multipart `UploadFile` objects
- `req.query.get("q")` and `req.query.getlist("tag")`
- `req.headers`, `req.cookies`, `req.path_params`, and `req.state`

The default request-body limit is 16 MiB; set `Night(max_body_size=...)` to change it. `UploadFile.read()` reads an upload and `UploadFile.save(path)` writes it to disk.

## Dataclass validation

```python
import dataclasses

@dataclasses.dataclass
class Address:
    city: str

@dataclasses.dataclass
class CreateUser:
    name: str
    tags: list[str]
    addresses: list[Address]

@app.post("/users", body=CreateUser)
def create_user(user: CreateUser):
    return {"name": user.name}
```

Night validates required fields, primitive values, `Optional[T]`, nested dataclasses, and `list[T]`. Failures return HTTP 422:

```json
{"errors":[{"field":"addresses[1].city","message":"Field is required"}]}
```

## Responses

Returning a `dict` or `list` produces JSON; a `str` produces text. Use `jsonify`, `text`, `html`, `redirect`, `stream`, `send_file`, and `clear_client_storage` for explicit responses.

`Response.set_cookie()` and `Response.delete_cookie()` support cookie attributes and multiple `Set-Cookie` headers.

### Chainable file responses and gzip

`send_file()` returns a lazy file handler. It can be returned from a route or registered directly:

```python
app.get("/manual", send_file("manual.pdf"))
app.get("/data", send_file("data.json").gz())
```

`send_file(...).gz(level)` serves an HTTP gzip representation with `Content-Encoding: gzip` and `Vary: Accept-Encoding`. The compressed representation is stored in the OS temporary directory and reused using a cache key derived from source path, nanosecond mtime, source size, and gzip level. Changing the source naturally creates a new cached representation.

Enable gzip as the default for Night file/static responses with `app.gz()`; use `.raw()` to opt an individual file out:

```python
app.gz(9).get("/data", send_file("data.json"))
app.get("/raw", send_file("data.json").raw())
```




## Endpoint response cache

For pure no-argument endpoints whose completed response can be reused, put `@app.cache` below the route decorator:

```python
@app.get("/catalog")
@app.cache
def catalog():
    return {"items": build_catalog()}
```

`@app.cache(ttl=30)` expires the snapshot after 30 seconds; the default `ttl=None` keeps it for the process lifetime. Cached responses are cloned on every hit so `HEAD`, cookies, and later response mutation cannot corrupt the shared snapshot. Responses carrying `Set-Cookie` and responses outside the 2xx/3xx range are not cached. The decorator intentionally supports no-argument endpoints only; request-dependent handlers should use an application-specific cache key instead.
