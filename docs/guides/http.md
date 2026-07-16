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


