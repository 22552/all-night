# デプロイ

Night 0.1.1 は Python 3.11+ を対象にしています。PyPI から `pip install all-night` で導入できます。

リポジトリには `Dockerfile`、`docker-compose.yml`、`render.yaml`、および `deploy/cloudflare-night` の Cloudflare Python Workers テンプレートがあります。

## ASGIサーバー

通常のPython環境では Uvicorn / Hypercorn などのASGIサーバーで動かします。

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

TLS終端やreverse proxyを使う場合は、外部requestのschemeがASGIへ正しく渡るようにしてください。Secure Cookieの判定に影響します。

## Docker

```bash
docker compose up --build
curl http://localhost:8000/health
```

自作アプリではmodule targetを `your_module:app` に変更するか、PyPIの `all-night` をinstallするprojectからimageをbuildします。

## Render / Railway

Renderでは `render.yaml`、Railwayではroot `Dockerfile` を利用できます。containerはplatformから渡される `PORT` を利用する構成にしてください。

## Cloudflare Python Workers

Nightは `Night.cloudflare_fetch()` と `Night.cloudflare_rpc()` でCloudflare Python Workersへ直接組み込めます。詳しくは [Cloudflare Python Workers](../guides/cloudflare-workers.md) を参照してください。

Cloudflareはdeploy時にトップレベルmodule初期化を実行し、初期化済みPyodideのWebAssembly linear memoryをsnapshotします。そのため `app = Night()` とroute登録はmodule scopeに置き、request固有stateやbinding I/Oはそこへ置かない構成が向いています。

repositoryのCloudflare templateはCIでbuild確認しています。compatibility dateは意図的に固定されているため、Python/Pyodide runtimeの挙動を確認せず更新しないでください。

## 本番運用

session / flash / CSRFを使う場合は、強い `secret_key` を環境変数などから渡してください。uploadに合わせて `max_body_size` も設定します。

署名付きsession dataはCookie側に保存されます。一方、application globalやmemory stateはprocess/isolate localです。複数instance間で整合性が必要なdataは外部storeへ置いてください。

Cloudflare Workersではrequestごとのuser stateをmodule globalに保存しないでください。warm isolateは複数requestを処理できます。

## PyPIリリース

現在の公開版は **all-night 0.1.1** です。

通常のrelease手順:

1. `pyproject.toml` のversionを上げる
2. full test matrixを通す
3. PyPIに同じversionが存在しないことを確認する
4. `v*` tagをpushして `Publish to PyPI` workflowを起動する
5. wheel / sdistのupload成功を確認する

```bash
git tag v0.1.2
git push origin v0.1.2
```

PyPI tokenをrepositoryへcommitしないでください。
