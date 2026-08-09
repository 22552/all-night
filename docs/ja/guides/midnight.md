# Midnight

## 0.1.5以降のインストール

Midnightは `standard` 構成のオプション機能になり、最小の `all-night` wheelには同梱されません。

```bash
python -m pip install -U "all-night[standard]"
```

このextraが別配布の `all-night-midnight` を導入し、`night_midnight`、`night_midnight_component`、`night_midnight_dev`、`night_midnight_form` を提供します。

Midnight は Browser Night の Python と表示中の HTML を双方向につなぐブリッジ拡張です。

通信は2系統に分かれます。

- **ローカルDOMブリッジ** — JavaScript がクリック・入力・submit などのイベントを捕捉し、`postMessage` 経由で同じタブ内の Pyodide/Python へ渡します。ローカル通信のためだけに WebSocket は使いません。
- **WebSocketブリッジ** — HTML 側で実際の WebSocket を開き、`open` / `message` / `close` / `error` を Python に転送できます。Python から connect/send/close もできます。

`all-night` に `night_midnight` モジュールとして含める設計で、別の `midnight` PyPI パッケージにはしません。

通常は `Midnight()` で明示的にインスタンスを作れます。`from night_midnight import midnight` は互換性と手軽さのための**遅延生成proxy**になり、importしただけでは共有状態を即座に生成しません。テストや独立したアプリでは普通に `Midnight()` を複数作れます。必要なら `reset_default_midnight()` で便利インスタンスを差し替えられます。

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

Browser Night以外でPyodideの`js`モジュールをimportできない場合だけ、commandは現在sessionのoutboxへfallbackします。`nightMidnightPush()`自体が存在しているのにJS側で例外を投げた場合は、silent failureにせずその例外をそのまま表へ出します。

## 複数ユーザー / 信頼境界

Browser Nightではブラウザーの各タブがそれぞれ別のPyodide/Python runtimeを持つため、ユーザーは自然に分離されます。一方、通常のCPythonサーバーでは1つのbridgeを複数クライアントが共有できるため、Midnightは`ContextVar`で選ばれる`MidnightSession`ごとに可変状態を分離します。

イベントhandlerとsubscriptionは全ユーザーで共有し、`midnight.state`、テンプレートbinding、Python→HTMLのoutboxだけがsession-localになります。

```python
@midnight.on_event("rename")
async def rename(event):
    midnight.set("name", event["name"])
    await do_something()
    midnight.text("#name", midnight.state["name"])
```

クライアント由来payloadを処理するAPIには、意図的に**`session_id`引数がありません**。

```python
commands = await midnight.dispatch_untrusted(event)
# midnight.dispatch(event) も同じ安全側APIの互換alias
```

共有CPythonサーバーで特定sessionを指定するadapterは、信頼境界をコード上で明示します。

```python
from night_midnight import trusted_session_id

session_id = trusted_session_id(authenticated_connection.id)
commands = await midnight.dispatch_trusted(session_id, event)

ws_commands = await midnight.dispatch_ws_trusted(session_id, ws_event)
```

`TrustedSessionId` は型チェッカー上で通常の `str` と区別でき、さらに `*_trusted` というAPI名でコードレビュー時にも信頼境界が見えます。ただし `trusted_session_id()` は**認証機能ではなく「この値を信頼済みとして扱う」という明示的なassertion**です。任意のブラウザーevent内に入っていたIDをそのまま包んではいけません。サーバー側の認証済みconnection/session情報から導出してください。

session bindingは`await`をまたいでも維持されるため、複数クライアントのasync handlerが同時に動いても別ユーザーのstateへ切り替わりません。

dispatch外から信頼済みsessionへ更新を送る場合も、API名で明示します。

```python
with midnight.trusted_session(session_id):
    midnight.set("unread", 3)
    midnight.emit("notification", {"count": 3})
```

主なsession API:

```python
midnight.session_id
midnight.current_session
midnight.get_session(session_id)
midnight.session_ids()
midnight.drop_session(session_id)
```

一時的な認証済みconnection/sessionが完全に切断され、そのメモリ上stateが不要になったら`drop_session()`で破棄できます。標準のsession storeはprocess-localなので、複数process/複数instance構成では永続・共有すべきアプリ状態は通常のDB/session backendへ保存し、MidnightSessionは接続単位のUI stateとして扱います。

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
認証済みconnection ID -> TrustedSessionId -> ContextVar
                      -> MidnightSession -> state + outbox
```

同じブラウザータブ内のPythonとHTMLの通信には軽いdirect bridgeを使い、WebSocketは外部との双方向通信が必要な場合だけ使う構成です。
