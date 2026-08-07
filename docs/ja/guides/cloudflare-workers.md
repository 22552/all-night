# Cloudflare Python Workers

Night は追加のASGI server processを置かず、Cloudflare Python Workersの中で直接動かせます。

Cloudflare Python WorkersはWorkers runtime内のPyodideでPythonを実行します。deploy時にはmoduleのtop-level初期化とimportを実行し、初期化済みWebAssembly linear memoryをsnapshotしてcold start時の初期化量を減らします。そのため `app = Night()` とroute登録はmodule scopeへ置き、request固有stateはrequest scopeに保持する構成が向いています。

Python Workersは現在betaです。compatibility date / flag / runtime SDKを変更するときはCloudflareの最新ドキュメントを確認してください。

## 基本形

完全なsampleは `deploy/cloudflare-night` にあります。

```python
from night import Night
from workers import WorkerEntrypoint

app = Night()

@app.get("/")
def index():
    return {"hello": "edge"}

class Default(WorkerEntrypoint):
    async def fetch(self, request):
        return await app.cloudflare_fetch(request)
```

`Night.cloudflare_fetch()` がWorkers RequestをNightのHTTP処理へ渡し、Night ResponseをWorkers Responseへ変換します。

Cloudflare固有moduleはbridge利用時だけ必要なので、通常のCPython環境ではNight coreの必須dependencyにはなりません。

## workers-runtime-sdk

`workers-runtime-sdk` はPython Workersのruntime API、型、FFI wrapper、RPC変換helperを提供します。NightはPython/JavaScript RPC valueを独自serializeせず、公式SDKの変換層を利用します。

## Workers RPC

Nightの `@app.rpc(...)` registryはHTTP JSON-RPCとWorkers RPCで共有できます。

```python
@app.rpc("add")
def add(a: int, b: int):
    return a + b
```

Worker entrypoint側:

```python
class Default(WorkerEntrypoint):
    async def fetch(self, request):
        return await app.cloudflare_fetch(request)

    async def night_rpc(self, method, args=None, kwargs=None):
        return await app.cloudflare_rpc(method, args, kwargs)
```

`cloudflare_rpc()` はincoming valueに `workers.rpc.python_from_rpc()`、戻り値に `workers.rpc.python_to_rpc()` を使います。

## Binding

Bindingは `WorkerEntrypoint` のenvironmentから利用できます。repositoryのToDo sampleはWorkers KVを使っています。

requestごとのuser stateをmodule globalへ保存しないでください。warm isolateは複数requestを処理します。

## Request body

現在の `cloudflare_fetch()` はGET/HEAD以外のbodyを読み込んでからNightへ渡し、`app.max_body_size` を確認します。default上限は16 MiBです。

大きいuploadを扱う場合はWorker memoryを意識してbody limitを保守的にしてください。Night本体の `Request.body()` は複数ASGI chunkを扱えるため、将来bridge側をstreaming化してもendpoint APIは維持できます。

## Cold start / first hit

Night側で意識するポイント:

- `app = Night()` とroute登録はmodule scopeへ置く
- deterministicなimport / route index構築はdeploy snapshotに載せる
- network accessやbinding I/Oをmodule初期化で行わない
- first request / second request / steady stateを分けて計測する
- compatibility dateを更新したらCloudflare template buildと実deployの両方を確認する

## 開発・deploy

Cloudflareの現在のPython Workers workflowでは `pywrangler` を利用します。

```bash
uv run pywrangler dev
uv run pywrangler deploy
```

Cloudflare公式ドキュメント:

- https://developers.cloudflare.com/workers/languages/python/
- https://developers.cloudflare.com/workers/languages/python/how-python-workers-work/
- https://developers.cloudflare.com/workers/runtime-apis/rpc/
