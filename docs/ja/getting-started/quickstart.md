# クイックスタート

`night.py` と同じ場所に `app.py` を作成します。

```python
from night import Night

app = Night(secret_key="random-secret")

@app.get("/")
def index():
    return {"message": "Hello, Night"}
```

ASGIサーバーで起動します。

```bash
uvicorn app:app --reload
```

組み込みCLIも使えます。

```bash
python night.py run app.py
python night.py routes
python night.py shell
```

`secret_key` は署名付きセッション、flash、CSRFを使う場合に必要です。本番では環境変数などから強い秘密値を渡してください。


