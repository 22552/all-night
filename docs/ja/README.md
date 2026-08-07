# Night ドキュメント

Night は Python 3.11+ 向けの、単一ファイルを中心にした ASGI Web フレームワークです。PyPI のパッケージ名は `all-night`、import 名は `night` です。

[English documentation](../README.md)

## はじめに

- [クイックスタート](getting-started/quickstart.md) — PyPI からの導入、CLI / ASGI サーバー、最初のアプリ
- [HTTPアプリケーション](guides/http.md) — ルーティング、Request/Response、フォーム、アップロード、検証
- [Cloudflare Python Workers](guides/cloudflare-workers.md) — `cloudflare_fetch`、Workers RPC、Service Binding、KV、Edge運用
- [セキュリティ](guides/security.md) — セッション、Cookie、CSRF、Lua macro
- [リアルタイム](guides/realtime.md) — SSE、WebSocket、lifespan、ストリーミング

## リファレンス

- [Application と Routing](reference/application.md)
- [Request / Response API](reference/request-response.md)
- [SQLite ORM](reference/orm.md)
- [CLI・テスト・拡張](reference/tooling.md)
- [デプロイ](operations/deployment.md)

## 設計

通常の CPython では Night のコアは必須runtime dependencyなしを維持します。`uvicorn`、`graphql-core`、`lupa`、Cloudflare の `workers-runtime-sdk` などは、それを使うアプリケーションだけが導入します。

ルーティングは登録時にできるだけ前処理されます。静的ルートのindex化、典型的な動的ルートのspecialize、endpointのcall shape分類、route固有invokerの生成を行い、request時の分岐や線形探索を減らしています。

## Cloudflareについて

Cloudflare Python Workers は Pyodide 上で動きます。Cloudflare は deploy 時にトップレベルの import / 初期化を実行し、WebAssembly linear memory を snapshot してcold start時の初期化コストを減らします。そのため `app = Night()` と route登録は module scope に置き、request固有の状態はglobalに保存しない構成が向いています。

Python Workers は現在 beta です。compatibility date / flag / runtime SDK を変更する場合は Cloudflare の最新ドキュメントを確認してください。

## バージョン

このドキュメントは **all-night 0.1.1 / Python 3.11+** を対象にしています。

AIコーディングエージェント向けの作業指針はリポジトリ直下の [`SKILL.md`](../../SKILL.md) を参照してください。
