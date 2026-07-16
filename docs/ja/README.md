# Night ドキュメント

Nightは単一ファイルで使えるASGI Webフレームワークです。このドキュメントは `night.py` の公開APIに対応しています。

[English documentation](../README.md)

## はじめに

- [クイックスタート](getting-started/quickstart.md) — 起動と最初のアプリ
- [HTTPアプリケーション](guides/http.md) — ルーティング、Request/Response、フォーム、検証
- [セキュリティ](guides/security.md) — セッション、Cookie、CSRF、Lua macro
- [リアルタイム](guides/realtime.md) — SSE、WebSocket、lifespan、ストリーミング

## リファレンス

- [Application と Routing](reference/application.md)
- [Request / Response API](reference/request-response.md)
- [CLI・テスト・拡張](reference/tooling.md)
- [デプロイ](operations/deployment.md)

Nightのコアは依存なしを維持します。`uvicorn`、`graphql-core`、`lupa` は必要なアプリケーションだけが任意で導入します。


