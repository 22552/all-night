# デプロイ

リポジトリには汎用の `Dockerfile`、`docker-compose.yml`、`render.yaml` を含めています。既定では `night:app` のサンプルアプリを配信します。

## ローカルコンテナ

```bash
docker compose up --build
curl http://localhost:8000/health
```

自作アプリを配信する場合は、Dockerfileの `night:app` を `your_module:app` に置き換えます。

## Render

1. GitHubリポジトリからRender Blueprintを作成します。
2. Renderが `render.yaml` を検出し、Dockerビルドと `/health` のヘルスチェックを行います。
3. 連携ブランチへのpushで自動デプロイされます。

## Railway

GitHubリポジトリからプロジェクトを作成します。RailwayはルートのDockerfileを自動検出します。コンテナはプラットフォームから渡される `PORT` を使用します。

## 本番運用

TLS終端・リバースプロキシを使う場合は、ASGIの `scheme` が正しく渡るよう設定してください。セッションCookieの `Secure` 属性に影響します。

本番では強い `secret_key` を環境変数などから渡し、アップロードに合わせて本文サイズ上限を設定してください。

内蔵セッションとアプリケーションのメモリ状態はプロセスローカルです。複数プロセスで共有・整合性が必要なデータは外部ストアに置いてください。

