# Night

`night.py` は、依存なしで使える単一ファイルの ASGI Web フレームワークです。Flask 風のルーティングと、ASGI らしい async・WebSocket・SSE を同居させています。

```python
from night import Night, jsonify

app = Night(secret_key="change-me")

@app.get("/")
def index():
    return {"hello": "night"}

@app.post("/echo")
async def echo(req):
    return jsonify(await req.json())
```

開発サーバーには Uvicorn を使います。

```bash
uvicorn app:app --reload
# または
python night.py run app.py
```

## Routing

`get`、`post`、`put`、`patch`、`delete`、`query`、`purge` を利用できます。GET ルートには HEAD が自動的に付き、OPTIONS も `Allow` ヘッダー付きで自動応答します。

```python
@app.get("/users/<int:user_id>", name="user")
def user(user_id: int):
    return {"id": user_id}

@app.query("/search")
async def search(req):
    return {"q": req.query.get("q", "")}

app.url_for("user", user_id=42)  # "/users/42"
```

コンバーターは `str`、`int`、`path` です。`Request.query` は簡易辞書、フォームの複数値は `QueryDict.getlist()` を使えます。

## Request と Response

```python
@app.post("/messages")
async def create_message(req):
    data = await req.json()
    form = await req.form()
    files = await req.files()
    return {"data": data, "title": form.get("title")}
```

- `await req.body()`、`await req.text()`、`await req.json()`
- `await req.form()`、`await req.files()`
- `req.headers`、`req.cookies`、`req.query`、`req.path_params`
- `req.client`、`req.url`、`req.state`
- `req.trace_id`、`req.span_id`、`req.trace_headers()`

リクエスト本文の上限は既定で16 MiBです。`Night(max_body_size=...)` で変更できます。multipart は上限内で解析され、アップロードは `UploadFile` として取得します。

戻り値が `dict` / `list` の場合はJSON、`str` の場合はテキストになります。明示的なレスポンスには `jsonify`、`text`、`html`、`redirect`、`stream`、`send_file` を使います。

```python
from night import redirect, stream

@app.get("/login")
def login():
    return redirect("/signin")
```

`Response.set_cookie()` と `Response.delete_cookie()` は Cookie 属性と複数の `Set-Cookie` ヘッダーを扱います。

## Body validation

dataclass を `body=` に渡すと、JSONボディを軽量に検証してハンドラーへ注入できます。不正な入力は422です。

```python
import dataclasses
from night import Request

@dataclasses.dataclass
class UserCreate:
    name: str
    age: int

@app.post("/users", body=UserCreate)
def create_user(req: Request, user: UserCreate):
    return {"name": user.name, "age": user.age}
```

必須フィールド、基本型、`Optional`、単一のネストdataclassを扱います。`list[Model]` などのコンテナ型は現時点では自動検証しません。

## Session / CSRF / flash

セッションは署名付きCookieです。内容は改ざん検知されますが暗号化はされないため、秘密情報を保存しないでください。

```python
from night import csrf_middleware, csrf_token, flash, get_flashed_messages, session

app = Night(secret_key="long-random-secret")
app.use(csrf_middleware())

@app.get("/form")
def form_page():
    return f'<input type="hidden" name="csrf_token" value="{csrf_token()}">'

@app.post("/profile")
def profile():
    session()["seen_profile"] = True
    flash("Saved", "success")
    return {"ok": True}
```

CSRFミドルウェアは POST / PUT / PATCH / DELETE / QUERY を対象に、`X-CSRF-Token` またはフォームの `csrf_token` を検証します。セッションサイズにはCookie上限に合わせた制限があります。

## Middleware, hooks, errors

```python
@app.before_request
def before(req):
    req.state["request_id"] = req.trace_id

@app.after_request
def after(req, resp):
    resp.headers["x-request-id"] = req.state["request_id"]
    return resp

@app.errorhandler(KeyError)
def key_error(req, exc):
    return jsonify({"error": "missing key"}, status=400)
```

`app.use(middleware)` では `(req, call_next)` 形式の async ミドルウェアを登録します。組み込みには `logger_middleware()`、`cors_middleware()`、`csrf_middleware()` があります。

## Router と Blueprint

```python
from night import Blueprint

api = Blueprint("api", url_prefix="/api/v1")

@api.get("/users")
def users():
    return []

api.register(app)
```

`Router` は `app.mount("/api", router)` でも登録できます。

## WebSocket と SSE

```python
@app.websocket("/ws")
async def websocket(ws):
    await ws.accept()
    await ws.send_json({"ready": True})
    message = await ws.receive_json()
    await ws.close()
```

SSEには `sse()` を使います。

```python
from night import sse

@app.get("/events")
async def events():
    async def source():
        yield {"event": "ping", "data": {"ok": True}}
    return sse(source())
```

## Lifespan, extensions, GraphQL, JSON-RPC

`@app.on_startup` と `@app.on_shutdown` はASGI lifespanイベントで実行されます。`app.register_extension()` で拡張を登録できます。

```python
@app.rpc("add")
def add(a, b):
    return a + b
```

JSON-RPCは `/rpc` に公開されます。GraphQLは任意依存の `graphql-core` を使い、`GraphQLExtension(schema)` を `register_extension` します。

Lua macroは任意依存の `lupa` を使う開発者向け機能です。信頼できないユーザー入力を実行するサンドボックスではありません。

## Static files, CSS, OpenAPI, CLI

```python
from night import static

app.mount("", static("./public"))
app.enable_css()
app.css({"body": {"margin": 0, "font-family": "system-ui"}})
```

CSSは `/_night/style.css` から配信されます。`app.openapi()` はOpenAPI 3.1の辞書を返します。CLIは `run`、`routes`、`shell` を提供します。

## Testing

```python
client = app.test_client()
response = client.get("/health")
assert response.status_code == 200
assert response.text
```

`TestClient` はASGIアプリをインプロセスで呼び出します。Cookieを保持するため、セッションを使うテストにも利用できます。

