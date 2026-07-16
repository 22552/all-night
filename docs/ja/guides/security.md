# セキュリティ

## 署名付きセッション

```python
from night import session, session_regenerate

@app.post("/login")
def login():
    session_regenerate()
    session()["user_id"] = "user-123"
    return {"ok": True}
```

セッションは署名付きCookieです。改ざんは検知できますが暗号化はされません。パスワードやアクセストークンなどの秘密情報を保存しないでください。

## CSRF

```python
from night import csrf_middleware

app.use(csrf_middleware())
app.enable_csrf_endpoint()
```

`GET /csrf-token` はJSONでトークンを返します。POST、PUT、PATCH、DELETE、QUERYでは `X-CSRF-Token` ヘッダー、またはフォームの `csrf_token` を検証します。

## Lua macro

Lua macroは信頼できるアプリケーションコード専用です。ユーザーが投稿したLuaを安全に実行するサンドボックスではありません。


