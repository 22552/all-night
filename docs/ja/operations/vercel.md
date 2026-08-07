# Vercel Functions

Night は ASGI application なので、Vercel の Python runtime が受け付ける `app` 変数としてそのまま公開できます。Vercel専用のRequest/Response変換adapterは不要です。

コピー可能な例は [`deploy/vercel-night`](../../../deploy/vercel-night) にあります。

## 最小構成

```python
from night import Night

app = Night()

@app.get("/")
def index():
    return {"hello": "vercel"}
```

Vercelが認識する `app.py` などを使うか、`pyproject.toml` でentrypointを指定します。

```toml
[tool.vercel]
entrypoint = "app.py"
```

依存とPython versionも `pyproject.toml` に書けます。

```toml
[project]
requires-python = ">=3.12"
dependencies = ["all-night>=0.1.1"]
```

## Deploy

Git連携でpushするか、Vercel CLIを使います。

```bash
vercel
```

このリポジトリのexampleを使う場合は `deploy/vercel-night` をproject rootにします。

## Streaming

Vercel Python runtimeはstreaming responseを扱えるため、Nightの `StreamingResponse` やSSE helperも通常のASGI responseとして利用できます。

## MCP + Vercel

MCP transportもNightのHTTP routeなので、同じVercel Functionで動かせます。

```python
from night import Night
from night_mcp import enable_mcp

app = Night()
mcp = enable_mcp(app)

@mcp.tool()
def add(a: int, b: int):
    return {"value": a + b}
```

MCP 2026-07-28 のstateless coreではsticky sessionや `Mcp-Session-Id` が不要なので、serverless deploymentと特に相性が良い構成です。

## 運用上の注意

- runtime dependencyとbundle対象ファイルを増やしすぎない。
- Vercelが現在サポートするPython versionを指定する。
- secretはenvironment variableへ置く。
- Vercel固有の挙動確認には `vercel dev` を使う。
- bundle size、memory、durationなどの具体的なlimitはVercel最新docsを確認する。

基本的なNight ASGI deploymentには `vercel.json` は不要です。durationやexcludeFilesなどVercel固有設定が必要な場合だけ追加してください。
