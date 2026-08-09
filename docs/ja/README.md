# Night ドキュメント

Night は Python **3.11+** 向けの、単一ファイルを中心にした ASGI Web フレームワークです。PyPI のパッケージ名は `all-night`、import 名は `night` です。通常の CPython コアは必須 runtime dependency なしを維持し、MCP・Cloudflare Workers・Pyodide・Midnight などの optional integration はコアの外側に分離しています。

[English documentation](../README.md)

## まず読むもの

初めて Night を使う場合は、次の順番がおすすめです。

1. [クイックスタート](getting-started/quickstart.md) — install、`app.py` 作成、起動、テスト
2. [HTTPアプリケーション](guides/http.md) — routing、Request/Response、file、form、validation、cookie、streaming
3. [Application と Routing](reference/application.md) — Night / Router の詳しいAPI
4. [Request / Response API](reference/request-response.md)
5. [CLI・テスト・拡張](reference/tooling.md)
6. [デプロイ](operations/deployment.md)

## 主な機能

### HTTP / Routing

- decorator / fluent route registration
- static / dynamic route
- typed path parameter
- automatic `HEAD` / `OPTIONS`
- named route / URL生成
- middleware / before / after hook / error handler
- JSON / text / HTML / redirect / streaming / file response
- form / multipart upload
- cookie / signed session / CSRF helper
- typed request body validation
- static file routing

### Realtime

- SSE
- WebSocket
- ASGI lifespan startup / shutdown
- streaming response

### UI / Template

- `${{ ... }}` template interpolation
- `if` / `for` / `include`
- filter / restricted expression
- Midnight Python ↔ HTML bridge
- form snapshot
- reusable component
- development hot reload

### Data / API

- SQLite ORM
- JSON-RPC 2.0
- OpenAPI generation
- stateless MCP tool exposure
- Cloudflare Workers RPC / Service Binding bridge

## ガイド

- [HTTPアプリケーション](guides/http.md)
- [テンプレート](guides/templates.md)
- [リアルタイム](guides/realtime.md)
- [セキュリティ](guides/security.md)
- [Midnight: Python ↔ HTML ブリッジ](guides/midnight.md)
- [Midnight Forms](guides/midnight-forms.md)
- [Midnightコンポーネント + Hot Reload](guides/midnight-components.md)
- [Browser Night](guides/browser.md)
- [Node.js runtime](guides/node.md)
- [Model Context Protocol](guides/mcp.md)
- [Cloudflare Python Workers](guides/cloudflare-workers.md)

## リファレンス

- [Application と Routing](reference/application.md)
- [Request / Response API](reference/request-response.md)
- [SQLite ORM](reference/orm.md)
- [CLI・テスト・RPC・拡張](reference/tooling.md)

## Runtime / Deploy

| Runtime | Nightの動かし方 | Docs |
| --- | --- | --- |
| CPython / ASGI | standard ASGI app | [Quickstart](getting-started/quickstart.md) |
| Vercel Functions | ASGI `app` を直接実行 | [Vercel](operations/vercel.md) |
| Cloudflare Python Workers | `cloudflare_fetch()` bridge | [Cloudflare](guides/cloudflare-workers.md) |
| Node.js 22 / 24 | Pyodide + `night_node.mjs` | [Node.js](guides/node.md) |
| Netlify Functions | Node adapter + Web Request/Response | [Netlify](operations/netlify.md) |
| Browser | Pyodide + `night_web` | [Browser Night](guides/browser.md) |

詳しくは [デプロイ概要](operations/deployment.md) を参照してください。

## CLIについて

基本的な起動は次の通りです。

```bash
night run app.py
night run app.py --host 0.0.0.0 --port 8080
```

0.1.5 の `night routes` / `night shell` はアプリファイル引数を受け取りません。以前のDocsにあった `night routes app.py` / `night shell app.py` は現行実装と一致しません。

## Browser Night と GitHub Pages

Browser Night は Pyodide を使い、Night application をブラウザタブ内だけで動かします。

現在の GitHub Pages workflow は **Markdown Docs ではなく Browser Night demo を公開**しています。ドキュメント本体の source of truth はリポジトリの `docs/` です。

## 設計

通常の CPython では Night のコアは必須 runtime dependency なしを維持します。`uvicorn`、`graphql-core`、`lupa`、Cloudflare の `workers-runtime-sdk` などは、それを使うアプリケーションだけが導入します。`night_mcp.py` も外部依存なしですが、single-file core と分離しています。

routing は登録時にできるだけ前処理されます。静的 route の index 化、典型的な dynamic route の specialize、endpoint の call shape 分類、route 固有 invoker の生成を行い、request 時の分岐や線形探索を減らしています。

portable Web runtime では transport 固有処理を routing core の外へ置きます。Node / Netlify は `night_node.mjs` + Pyodide + `night_web`、Browser Night はタブ内から同じ `night_web` bridge を利用します。

## バージョン

現在の PyPI release は **all-night 0.1.5**、必要 Python は **3.11+** です。

Midnight は `night_midnight`、`night_midnight_component`、`night_midnight_dev`、`night_midnight_form` として `all-night` に同梱されており、別 PyPI package ではありません。

AIコーディングエージェント向けの作業指針はリポジトリ直下の [`SKILL.md`](../../SKILL.md) を参照してください。
