# Node.js runtime

Nightは **Node.js 22 / 24を公式サポート**します。両方をCIで実行し、`night_node.mjs` がWeb標準の `Request` / `Response` とNightをPyodide経由で接続します。

```text
Node Request
  -> night_node.mjs
  -> Pyodide
  -> night_web.handle_web
  -> Night
  -> Web Response
```

## 必要環境

- Node.js 22以上。CI対象は22と24。
- repositoryで固定しているnpm版Pyodide。
- `night.py`、`night_web.py`、`app.py` を含むsource directory。`night_request_info.py` があればそれも読み込みます。

repository rootで依存を入れます。

```bash
npm install
```

## 例

`python/app.py`:

```python
from night import Night

app = Night()
app.get("/", lambda: {"hello": "node"})
```

Node側:

```js
import { createNightNodeHandler } from "./night_node.mjs";

const night = createNightNodeHandler({ sourceDir: "python" });
const response = await night(new Request("https://night.local/"));
console.log(response.status, await response.text());
```

## warm runtime

Pyodide interpreterとNight applicationはNode process内で一度初期化し、warmなrequest間で再利用します。Pyodide globalsを使う小さなbridge部分はrequestを直列化し、同時requestが互いのmethod / URL / bodyを上書きしないようにしています。

## platform情報

`platform` / `platformInfo` からhost側の信頼できるmetadataをNight request infoへ渡せます。

## 現在の制限

Node bridgeはrequest/response bodyをbufferします。WebSocketとstreaming responseはruntime固有bridgeが別途必要です。またPython側のfilesystem依存機能は、明示的にhost filesystemへbridgeしない限りPyodideのvirtual filesystemを使います。
