# Browser Night

Browser Nightは、Pyodideを使ってNight application全体をブラウザーのタブ内で動かすruntimeです。Pythonをブラウザーに読み込み、`night.py`・`night_web.py`・`app.py`をPyodideのin-memory filesystemへ配置し、Web形式のrequestを `night_web.handle_web` 経由でNightのrouting coreへ渡します。

デプロイ版ではPython HTTP serverは不要です。

## 構成

- `deploy/browser-night/404.html` — Browser Nightのshell兼SPA fallback。GitHub Pages deploy時には同じ内容を `index.html` にもコピーします。
- `deploy/browser-night/app.py` — Pyodide内で実行するNight app。
- `deploy/browser-night/debug.html` — local開発用のrequest console。
- `deploy/browser-night/sw.js` — Pyodide runtimeの永続cache。
- `night_web.py` — Web request/responseとNightをつなぐadapter。

## Pyodide cache

cold startで最も重いPyodide runtimeを毎回取り直さないよう、起動前にService Workerを登録します。`sw.js` はCache Storageの `night-pyodide-v1` を使い、version付きjsDelivr Pyodide pathだけをcache-firstで処理します。

そのため `pyodide.mjs`、WebAssembly runtime、package index、`sqlite3` など一度読み込んだpackageを次回以降に再利用できます。初回はnetwork accessが必要です。またブラウザーのstorage evictionやprivate modeではcacheが保持されない場合があります。

Service Workerがcacheするのはversion付きPyodide assetだけです。Night本体や `app.py` はこの大容量cacheへ固定しないため、framework/app更新時にPyodide cacheまで消す必要はありません。cache仕様を変える場合は `sw.js` のcache名を上げると、activate時に古い `night-pyodide-*` cacheを削除します。

## 例

```python
from night import Night

app = Night()
app.get("/", lambda: {"hello": "browser"})
```

## localで試す

```bash
python -m http.server 8000 -d deploy/browser-night
```

`http://localhost:8000/debug.html` を開きます。Service WorkerはHTTP/HTTPSが必要です（localhostは利用可能）。`file://` 直開きでは永続Pyodide cacheは使えません。

## 現在の制限

Browser adapterは現在request/response bodyをbufferします。WebSocketとstreaming responseのbrowser bridgeは未実装です。またnetwork/storage APIは通常のserver processではなくbrowserのorigin/CORS/security modelに従います。
