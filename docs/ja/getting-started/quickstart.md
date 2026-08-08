# クイックスタート

Night **0.1.4** は Python **3.11+** を対象にしています。PyPI のパッケージ名は `all-night`、import 名は `night` です。

## インストール

```bash
python -m pip install -U all-night
```

`night run` を使う場合は ASGI サーバーとして Uvicorn も入れます。

```bash
python -m pip install -U uvicorn
```

`app.py` を作成します。

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

## 起動

Night CLI で起動:

```bash
night run app.py
```

host / port も指定できます。

```bash
night run app.py --host 0.0.0.0 --port 8080
```

Uvicorn を直接使う場合:

```bash
uvicorn app:app --reload
```

通常の Night コア自体は Uvicorn を必須依存にしていません。現在の `night run` 実装または Uvicorn をサーバーとして選ぶ場合だけ必要です。

> **CLIについて:** 0.1.4 の `night routes` と `night shell` はアプリファイル引数を受け取りません。以前の `night routes app.py` / `night shell app.py` という例は現行実装と一致しないため削除しました。

## ルートを追加する

デコレータ形式と fluent 形式の両方が使えます。

```python
@app.post("/echo")
async def echo(req):
    return {"received": await req.json()}

app.get("/health", lambda: {"ok": True})
```

動的パスも使えます。

```python
@app.get("/posts/<int:post_id>")
def post(post_id: int):
    return {"post_id": post_id}
```

## Requestデータ

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

Night は JSON だけでなく、フォーム、multipart upload、Cookie、session、typed body validation、streaming、static file、SSE、WebSocket にも対応します。

## セッション

署名付きセッション、flash、CSRF helperを使う場合だけ `secret_key` を設定します。

```python
import os
from night import Night

app = Night(secret_key=os.environ["NIGHT_SECRET_KEY"])
```

本番用の secret をコードへ直書きしないでください。

## サーバーなしでテスト

```python
with app.test_client() as client:
    response = client.get("/users/42")
    assert response.status_code == 200
    assert response.get_json() == {"id": 42}
```

`TestClient` は ASGI アプリを in-process で実行し、request ごとに新しい event loop を作らず `asyncio.Runner` を再利用します。

## Nightを動かせる場所

- 通常の CPython / ASGI
- Vercel Functions
- Cloudflare Python Workers
- Node.js 22 / 24 + Pyodide
- Netlify Functions
- Browser Night / Pyodide

詳しくは [デプロイ](../operations/deployment.md) を参照してください。

## 次に読む

- [ドキュメント一覧](../README.md)
- [HTTPガイド](../guides/http.md)
- [Realtime](../guides/realtime.md)
- [Browser Night](../guides/browser.md)
- [Cloudflare Python Workers](../guides/cloudflare-workers.md)
- [デプロイ](../operations/deployment.md)
