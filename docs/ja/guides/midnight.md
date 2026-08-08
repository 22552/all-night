# Midnight

Midnight は Browser Night の Python と表示中の HTML を双方向につなぐブリッジ拡張です。

通信は2系統に分かれます。

- **ローカルDOMブリッジ** — JavaScript がクリック・入力・submit などのイベントを捕捉し、`postMessage` 経由で同じタブ内の Pyodide/Python へ渡します。ローカル通信のためだけに WebSocket は使いません。
- **WebSocketブリッジ** — HTML 側で実際の WebSocket を開き、`open` / `message` / `close` / `error` を Python に転送できます。Python から connect/send/close もできます。

`all-night` に `night_midnight` モジュールとして含める設計で、別の `midnight` PyPI パッケージにはしません。

## Nightテンプレート + Midnight

汎用テンプレートの根幹は `night.py` 本体の `TemplateEngine` が担当します。Midnightは別parserを持たず、`MidnightTemplateEngine` がコアEngineを継承してlive bindingだけ追加します。

```python
from night_midnight import midnight

@app.get("/")
def home():
    return midnight.render_template_string("""
      <h1>${{ title }}</h1>
      <p>${{ count }}</p>
      ${% if count > 0 %}<strong>Started</strong>${% endif %}
    """, title="Night", count=0)
```

単純な値埋め込みには `data-midnight-bind` が付き、ページ全体を再描画せずPythonから更新できます。

```python
midnight.set("count", 1)
```

ファイルテンプレートも `midnight.render_template("page.html", ...)` で同じEngineを使います。構文や拡張方法は[テンプレート](templates.md)を参照してください。

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

## 複数ユーザー / サーバーセッション

Browser Nightではブラウザーの各タブがそれぞれ別のPyodide/Python runtimeを持つため、ユーザーは自然に分離されます。一方、通常のCPythonサーバーでは1つの`midnight`を複数クライアントが共有できるため、Midnightは`ContextVar`で選ばれる`MidnightSession`ごとに可変状態を分離します。

イベントhandlerとsubscriptionは全ユーザーで共有し、`midnight.state`、テンプレートbinding、Python→HTMLのoutboxだけがsession-localになります。

```python
@midnight.on_event("rename")
async def rename(event):
    midnight.set("name", event["name"])
    await do_something()
    midnight.text("#name", midnight.state["name"])
```

サーバーadapterはイベントdispatch時に、接続や認証から得た安定したsession/connection IDを渡します。

```python
commands = await midnight.dispatch(
    event,
    session_id=trusted_connection_id,
)

ws_commands = await midnight.dispatch_ws(
    ws_event,
    session_id=trusted_connection_id,
)
```

session bindingは`await`をまたいでも維持されるため、複数クライアントのasync handlerが同時に動いても別ユーザーのstateへ切り替わりません。

dispatch外から特定ユーザーへ更新を送る場合は明示的にsessionをbindできます。

```python
with midnight.session(user_id):
    midnight.set("unread", 3)
    midnight.emit("notification", {"count": 3})
```

主なsession API:

```python
midnight.session_id
midnight.current_session
midnight.get_session("alice")
midnight.session_ids()
midnight.drop_session("alice")
```

一時的なconnection/sessionが完全に切断され、そのメモリ上stateが不要になったら`drop_session()`で破棄できます。標準のsession storeはprocess-localなので、複数process/複数instance構成では永続・共有すべきアプリ状態は通常のDB/session backendへ保存し、MidnightSessionは接続単位のUI stateとして扱います。

重要: `session_id`はブラウザーから送られてきた任意値をそのまま信用せず、サーバー側の認証済みconnection/session情報から決定してください。

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

共有CPythonサーバー:
connection/session ID -> ContextVar -> MidnightSession -> state + outbox
```

同じブラウザータブ内のPythonとHTMLの通信には軽いdirect bridgeを使い、WebSocketは外部との双方向通信が必要な場合だけ使う構成です。
