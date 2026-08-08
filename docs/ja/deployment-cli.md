# CLI からデプロイする

Night プロジェクトは `nightctl.py` の `deploy` サブコマンドからデプロイできます。
CLI 本体は Python 標準ライブラリだけで動作し、認証情報をリポジトリへ保存しません。

## Render

Render の対象サービスで Deploy Hook を作成し、環境変数へ設定します。

```bash
export RENDER_DEPLOY_HOOK='https://api.render.com/deploy/...'
python nightctl.py deploy
```

一回だけ指定する場合は `--hook` も使えますが、シェル履歴にURLが残る可能性があるため環境変数を推奨します。

```bash
python nightctl.py deploy --provider render --hook "$RENDER_DEPLOY_HOOK"
```

## Railway

Railway CLI でログイン・プロジェクト接続を済ませた後に実行します。

```bash
python nightctl.py deploy --provider railway
python nightctl.py deploy --provider railway --detach
```

## Fly.io

`flyctl` でログインし、必要なら `fly launch` で初期設定してから実行します。

```bash
python nightctl.py deploy --provider fly
python nightctl.py deploy --provider fly --remote-only
```

## Docker イメージをビルド

クラウドへ送信せず、デプロイ可能なコンテナイメージだけ作ることもできます。

```bash
python nightctl.py deploy --provider docker --image all-night:latest
python nightctl.py deploy --provider docker --platform linux/amd64
```

## 実行内容だけ確認する

```bash
python nightctl.py deploy --provider docker --dry-run
```

`--dry-run` はコマンドやHTTPリクエストの種類だけ表示し、実際のビルド・デプロイを行いません。Deploy Hook のURLは表示されません。

## 別ディレクトリを対象にする

```bash
python /path/to/nightctl.py deploy --project /path/to/project --provider docker
```

## 既存CLIとの互換性

`deploy` 以外は従来の `night.py` CLI に委譲されます。

```bash
python nightctl.py run app.py --host 0.0.0.0 --port 8000
python nightctl.py routes
python nightctl.py shell
```
