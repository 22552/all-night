# Sessions and security

## Signed sessions

```python
from night import session, session_regenerate

app = Night(secret_key="long-random-value")

@app.post("/login")
def login():
    session_regenerate()
    session()["user_id"] = "user-123"
    return {"ok": True}
```

Sessions are signed Cookie payloads. They prevent tampering but are not encrypted: do not put passwords, access tokens, or other secrets in them. Night limits the Cookie size and only sends an updated Cookie when session data changed.

Use `session_clear()` to clear it. `flash()` and `get_flashed_messages()` use the same session.

## CSRF

```python
from night import csrf_middleware

app.use(csrf_middleware())
app.enable_csrf_endpoint()  # GET /csrf-token -> {"csrf_token": "..."}
```

The middleware validates POST, PUT, PATCH, DELETE, and QUERY requests. Send the token as `X-CSRF-Token`, or as `csrf_token` in an HTML form. CSRF requires `secret_key` because it stores the token in the signed session.

## Lua macros

Lua macros are for trusted application code only. They are not a sandbox for untrusted user-authored scripts. Execute untrusted code in a separately isolated process or container.


