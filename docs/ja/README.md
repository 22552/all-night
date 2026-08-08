# Night ドキュメント

Night は Python 3.11+ 向けの、単一ファイルを中心にした ASGI Web フレームワークです。PyPI のパッケージ名は `all-night`、import 名は `night` です。MCPなどのoptional integrationはコアの外側に分離し、`night.py` 自体の依存なし設計を維持します。

[English documentation](../README.md)

## はじめに

- [クイックスタート](getting-started/quickstart.md) — PyPI からの導入、CLI / ASGI サーバー、最初のアプリ
- [HTTPアプリケーション](guides/http.md) — ルーティング、チェーン登録、Request/Response、gzipファイル配信、フォーム、検証
- [テンプレート](guides/templates.md) — `${{ ... }}`、if/for/include、制限付き式、filter、拡張用TemplateEngine
- [Node.js runtime](guides/node.md) — Pyodide + Web標準Request/ResponseでNode 22 / 24を公式サポート
- [Midnight: Python ↔ HTML ブリッジ](guides/midnight.md)
- [Midnight Forms](guides/midnight-forms.md) — 入力中のform snapshot、`FormSnapshot`、`getone()`、`getlist()`
- [Midnightコンポーネント + Hot Reload](guides/midnight-components.md) — selector/namespace付き再利用UIとstdlib-only WebSocket開発reload
- [Browser Night](guides/browser.md) — Pyodideでブラウザー内にNightを起動し、runtime assetを永続キャッシュ
- [Model Context Protocol](guides/mcp.md) — Night RPCをstateless MCP 2026-07-28 toolとして公開
- [Cloudflare Python Workers](guides/cloudflare-workers.md) — `cloudflare_fetch`、Workers RPC、Service Binding、KV、Edge運用
- [セキュリティ](guides/security.md) — セッション、Cookie、CSRF、Lua macro
- [リアルタイム](guides/realtime.md) — SSE、WebSocket、lifespan、ストリーミング

## リファレンス

- [Application と Routing](reference/application.md)
- [Request / Response API](reference/request-response.md)
- [SQLite ORM](reference/orm.md)
- [CLI・テスト・拡張](reference/tooling.md)
- [デプロイ](operations/deployment.md)
- [Vercel Functions](operations/vercel.md)
- [Netlify Functions](operations/netlify.md)

## 設計

通常の CPython では Night のコアは必須runtime dependencyなしを維持します。`uvicorn`、`graphql-core`、`lupa`、Cloudflare の `workers-runtime-sdk` などは、それを使うアプリケーションだけが導入します。`night_mcp.py` も外部依存なしですが、single-file coreと分離しています。

ルーティングは登録時にできるだけ前処理されます。静的ルートのindex化、典型的な動的ルートのspecialize、endpointのcall shape分類、route固有invokerの生成を行い、request時の分岐や線形探索を減らしています。

portable Web runtimeではtransport固有処理をrouting coreの外へ置きます。Node / Netlifyは `night_node.mjs` + Pyodide + `night_web`、Browser Nightはタブ内から同じ `night_web` bridgeを利用します。

## Serverless / Edge

- **Cloudflare Python Workers** — Workers Request/Response bridgeとWorkers RPCに対応。
- **Vercel Functions** — Vercel Python runtimeからNightのASGI `app`を直接実行可能。
- **Node.js 22 / 24** — `night_node.mjs` + Pyodideを両Node lineでCI実行する公式runtime。
- **Netlify Functions / Node 24** — modern Request/Response Function wrapperを公式CI対象にし、`deploy/netlify-night` にtemplateを用意。
- **Browser / Pyodide** — `night_web`を介して同じNight appをタブ内で実行。version付きPyodide assetはService Workerで再利用します。
- **MCP** — 通常のNight HTTP routeなので、ASGI / Cloudflare / Vercelなど通常のHTTP routeを運べるadapter上で同じMCP serverを動かせます。

## Cloudflareについて

Cloudflare Python Workers は Pyodide 上で動きます。Cloudflare は deploy 時にトップレベルの import / 初期化を実行し、WebAssembly linear memory を snapshot してcold start時の初期化コストを減らします。そのため `app = Night()` と route登録は module scope に置き、request固有の状態はglobalに保存しない構成が向いています。

Python Workers は現在 beta です。compatibility date / flag / runtime SDK を変更する場合は Cloudflare の最新ドキュメントを確認してください。

## バージョン

現在のPyPI releaseは **all-night 0.1.4 / Python 3.11+** です。0.1.3 には Midnight の `night_midnight`、`night_midnight_component`、`night_midnight_dev`、`night_midnight_form` が同梱されています。Midnight は別PyPIパッケージではなく `all-night` の一部です。

AIコーディングエージェント向けの作業指針はリポジトリ直下の [`SKILL.md`](../../SKILL.md) を参照してください。
