# HTTPアプリケーション

## ルーティング

```python
@app.get("/users/<int:user_id>", name="user")
def get_user(user_id: int):
    return {"id": user_id}
```

`get`、`post`、`put`、`patch`、`delete`、`query`、`purge` を使えます。GETにはHEADが自動対応し、OPTIONSには `Allow` ヘッダー付きで応答します。パス変換は `str`、`int`、`path` です。

handlerを直接渡す明示登録・チェーン登録にも対応しています。

```python
def home():
    return "home"

app.add_route("GET", "/health", lambda: {"ok": True})
app.get("/", home).get("/about", lambda: "about")
```

handlerを省略した `@app.get("/path")` は従来どおりdecoratorとして動きます。

## 入力

- `await req.body()`、`await req.text()`、`await req.json()`
- `await req.form()`、`await req.files()`
- `req.query.get("q")`、`req.query.getlist("tag")`
- `req.headers`、`req.cookies`、`req.path_params`、`req.state`

本文サイズ上限の既定値は16 MiBです。`Night(max_body_size=...)` で変更できます。

## dataclassバリデーション

```python
import dataclasses

@dataclasses.dataclass
class CreateUser:
    name: str
    tags: list[str]

@app.post("/users", body=CreateUser)
def create_user(user: CreateUser):
    return {"name": user.name}
```

必須フィールド、基本型、`Optional[T]`、ネストしたdataclass、`list[T]`を検証します。失敗時はHTTP 422で次のようなJSONを返します。

```json
{"errors":[{"field":"tags","message":"Expected a list"}]}
```

辞書・リストはJSON、文字列はテキストとして返されます。明示的なレスポンスには `jsonify`、`text`、`html`、`redirect`、`stream`、`send_file` を利用できます。

## ファイル配信とgzip

`send_file()` は遅延評価されるfile handlerを返すため、そのままrouteへ登録できます。

```python
app.get("/file", send_file("data.json"))
app.get("/file.gz", send_file("data.json").gz())
```

`.gz(level)` はHTTPの `Content-Encoding: gzip` として配信し、圧縮済みデータをOSの一時ディレクトリへキャッシュします。cache keyは元ファイルの絶対path・mtime(ns)・size・gzip levelから作るため、元ファイルを更新すると自動的に別cacheへ切り替わります。

`app.gz()` を使うと `send_file()` / `static()` のデフォルトをgzipにできます。個別に無効化する場合は `.raw()` を使います。

```python
app.gz().get("/data", send_file("data.json"))
app.get("/raw", send_file("data.json").raw())
```


