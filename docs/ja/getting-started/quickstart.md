# クイックスタート

Night 0.1.1 は Python 3.11+ を対象にしています。

## インストール

```bash
python -m pip install -U all-night
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

Uvicorn を使う場合:

```bash
python -m pip install uvicorn
uvicorn app:app --reload
```

Night の CLI も使えます。

```bash
night run app.py
night routes app.py
night shell app.py
```

## JSON入力

```python
@app.post("/echo")
async def echo(req):
    return {"received": await req.json()}
```

## セッション

署名付きセッション、flash、CSRF helperを使う場合だけ `secret_key` を設定します。

```python
import os
from night import Night

app = Night(secret_key=os.environ["NIGHT_SECRET_KEY"])
```

本番のsecretをコードへ直書きしないでください。

## サーバーなしでテスト

```python
with app.test_client() as client:
    response = client.get("/users/42")
    assert response.status_code == 200
    assert response.get_json() == {"id": 42}
```

`TestClient` はASGIアプリをin-processで実行し、requestごとに新しいevent loopを作らず `asyncio.Runner` を再利用します。

次は [HTTPガイド](../guides/http.md)、[Cloudflare Python Workers](../guides/cloudflare-workers.md)、[デプロイ](../operations/deployment.md) を参照してください。
