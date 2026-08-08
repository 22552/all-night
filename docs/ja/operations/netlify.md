# Netlify Functions

Nightは **Netlify Functions / Node.js 24を公式サポート**します。すぐ使えるtemplateは [`deploy/netlify-night`](../../../deploy/netlify-night) にあります。

Netlify FunctionsはWeb標準の `Request` / `Response` を使うため、platform固有コードは共通Node adapterの薄いwrapperだけです。

```ts
import type { Config, Context } from "@netlify/functions";
import { createNightNodeHandler } from "./_shared/night_node.mjs";

const night = createNightNodeHandler({
  sourceDir: new URL("./_python/", import.meta.url),
  platform: "netlify",
});

export default (request: Request, context: Context) => night(request, context);

export const config: Config = { path: "/*" };
```

legacy Lambda形式の `exports.handler` は公式templateでは使いません。

## build

`npm run prepare` で現在のrepositoryから以下をFunction bundleへvendorします。

- `night.py`
- `night_web.py`
- `night_request_info.py`
- `python/app.py`
- `night_node.mjs`

request時にGitHubやPyPIからNightをdownloadする必要はありません。Pyodide runtimeとNight appはwarm Function instance内で再利用します。

## local実行

```bash
cd deploy/netlify-night
npm install
npm run dev
```

templateは `netlify.toml` でNode 24を指定します。共通Node adapter自体はNode 22 / 24の両方をCI対象にしています。

## deploy

Git連携ではbase directoryを `deploy/netlify-night` に設定します。CLIなら次の形です。

```bash
cd deploy/netlify-night
netlify link
netlify deploy
netlify deploy --prod
```

secretはrepositoryの `netlify.toml` に書かず、Netlify側のenvironment variableへ設定してください。

## request metadata

Netlify `Context` から取得できるclient IP、request ID、country、city、timezone、緯度・経度などをNightのrequest infoへ渡します。

## 現在の制限

Node/Pyodide bridgeはHTTP bodyをbufferします。WebSocketとstreaming responseのNetlify bridgeは未実装です。またcold startにはPyodide初期化が含まれるため、native JavaScript Functionより起動サイズを重視する構成ではありません。
