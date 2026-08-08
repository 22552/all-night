# Midnight コンポーネントと Hot Reload

Midnightには、再利用UIを名前空間付きで扱う`Component`と、Nightの既存WebSocketを使った依存なしの開発用Hot Reloadを追加できます。

## Component

`Component`は別のイベントシステムを作らず、既存Midnight APIへ2種類のスコープを付けます。

- DOMイベント/更新用のCSS root selector
- custom event/live binding用の論理namespace

```python
from night_midnight import midnight
from night_midnight_component import Component

profile = Component("#profile", name="profile", bridge=midnight)

@profile.on("click", ".close")
def close(event):
    profile.remove_class("&", "open")
    profile.set("visible", False)
    profile.emit("closed")
```

`.close`は内部では`#profile .close`として登録されます。`&`はcomponent root自身を表すので、`& > header`は`#profile > header`になります。

bindingとcustom eventもnamespace化されます。

```python
profile.set("visible", True)   # profile.visible
profile.emit("closed")        # profile:closed

@profile.on_event("closed")
def closed(event):
    ...
```

そのため、同じローカルselector名を持つUIを複数配置できます。

```python
left = Component("#left-tabs", name="left")
right = Component("#right-tabs", name="right")
```

`Component`は公開`Midnight` APIへ委譲するだけなので、session分離やBrowser Nightのdirect bridgeもそのまま使われます。

## stdlib-only Hot Reload

`HotReload`は`night_midnight_dev`に分離してあり、本番のMidnight importでwatcherが起動することはありません。実装に使うのは以下だけです。

- Night標準の`@app.websocket(...)`
- `os.stat()`による更新検知
- `asyncio.sleep()`によるpolling
- `watchdog`などの追加依存なし

全体reload:

```python
from night import Night
from night_midnight_dev import HotReload

app = Night()
dev = HotReload(app, ["app.py", "templates"], interval=0.35)

@app.get("/")
def home():
    return f"""
    <main>Hello</main>
    {dev.client_script()}
    """
```

ブラウザーは`/__midnight_reload`へWebSocket接続します。監視ファイルの`(mtime_ns, size)` snapshotが変わると`{"type":"reload"}`をbroadcastし、ブラウザーが`location.reload()`します。

ディレクトリは再帰的に監視し、`.git`、`__pycache__`、`.venv`、`venv`、`node_modules`は無視します。

## Component単位の部分更新

独立してrenderできるUIなら、ページ全体ではなくその領域だけを差し替えられます。

```python
card = Component("#card", name="card")

def render_card():
    return "<strong>fresh card</strong>"

card_reload = HotReload(
    app,
    ["components/card.py", "templates/card.html"],
    mode="component",
    selector=card.root,
    render=render_card,
)
```

`render`はsync/async両方に対応します。変更時は`component` WebSocket messageを送り、開発clientが対象selectorの`innerHTML`だけを更新します。

Hot Reloadは開発補助機能です。本番の状態同期は従来どおりNight/Midnight session、WebSocket、DBなどを使います。
