# Midnight

Midnight は Browser Night の Python と表示中の HTML を双方向につなぐブリッジ拡張です。

通信は2系統に分かれます。

- **ローカルDOMブリッジ** — JavaScript がクリック・入力・submit などのイベントを捕捉し、`postMessage` 経由で同じタブ内の Pyodide/Python へ渡します。ローカル通信のためだけに WebSocket は使いません。
- **WebSocketブリッジ** — HTML 側で実際の WebSocket を開き、`open` / `message` / `close` / `error` を Python に転送できます。Python から connect/send/close もできます。

`all-night` に `night_midnight` モジュールとして含める設計で、別の `midnight` PyPI パッケージにはしません。

## HTML → Python

```python
from night_midnight import midnight

@midnight.on("click", "#save")
def save(event):
    midnight.text("#status", "Pythonで保存しました")

@midnight.on("submit", "#login", prevent_default=True)
async def login(event):
    form = event.get("form") or {}
    midnight.emit("login-result", {"user": form.get("user")})
```

DOMオブジェクトそのものではなく、`type`、`selector`、`target`、キーボード/マウス情報、フォーム値などの小さなイベントスナップショットをPythonへ渡します。

HTML側から独自イベントも送れます。

```html
<button onclick="midnight.emit('hello', {name: 'Night'})">Hello</button>
```

```python
@midnight.on_event("hello")
def hello(event):
    midnight.emit("hello-back", event["detail"])
```

## Python → HTML

任意JavaScriptの `eval` ではなく、構造化されたDOM操作を使います。

```python
midnight.text("#status", "Ready")
midnight.html("#panel", "<strong>Done</strong>")
midnight.value("#name", "Ada")
midnight.attr("#name", "aria-label", "Name")
midnight.add_class("#panel", "ready")
midnight.remove_class("#panel", "hidden")
midnight.focus("#name")
midnight.emit("updated", {"count": 3})
```

HTML側はPythonからのイベントを受け取れます。

```js
midnight.on("updated", detail => {
  console.log(detail.count)
})
```

## WebSocket

```python
@midnight.on_ws("open")
def opened(event):
    midnight.ws_send({"hello": "Night"}, socket_id=event["socket_id"])

@midnight.on_ws("message")
def message(event):
    print(event.get("data"), event.get("json"))

midnight.ws_connect("wss://example.com/socket", socket_id="chat")
```

HTMLから直接開くこともできます。

```js
midnight.connect("wss://example.com/socket", {socketId: "chat"})
midnight.send({hello: "Night"}, "chat")
```

## 構成

```text
HTML DOM event ─┐
                ├─ midnight.js ─ postMessage ─ Pyodide ─ night_midnight.py
WebSocket event ┘                                  │
                                                  │ 構造化command
                                                  ▼
HTML DOM / CustomEvent / WebSocket
```

同じブラウザータブ内のPythonとHTMLの通信には軽いdirect bridgeを使い、WebSocketは外部との双方向通信が必要な場合だけ使う構成です。
