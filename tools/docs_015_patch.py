from pathlib import Path


def prepend_after_title(path: str, marker: str, block: str) -> None:
    p = Path(path)
    text = p.read_text(encoding='utf-8')
    text = text.replace('0.1.4', '0.1.5')
    if marker not in text:
        first_break = text.find('\n\n')
        if first_break < 0:
            raise SystemExit(f'no title break in {path}')
        text = text[: first_break + 2] + block.rstrip() + '\n\n' + text[first_break + 2 :]
    p.write_text(text, encoding='utf-8')


def append_once(path: str, marker: str, block: str) -> None:
    p = Path(path)
    text = p.read_text(encoding='utf-8').replace('0.1.4', '0.1.5')
    if marker not in text:
        text = text.rstrip() + '\n\n' + block.rstrip() + '\n'
    p.write_text(text, encoding='utf-8')


for path in ('docs/README.md', 'docs/ja/README.md'):
    p = Path(path)
    p.write_text(p.read_text(encoding='utf-8').replace('0.1.4', '0.1.5'), encoding='utf-8')

prepend_after_title(
    'docs/getting-started/quickstart.md',
    '### Install profiles (0.1.5)',
    '''### Install profiles (0.1.5)

Minimal Night stays dependency-free:

```bash
python -m pip install -U all-night
```

For the recommended CPython server stack, Midnight, and Cloudflare runtime typings:

```bash
python -m pip install -U "all-night[standard]"
```

The standard profile installs `uvicorn[standard]`, `orjson`, `workers-runtime-sdk` on Python 3.13+, and the separate `all-night-midnight` distribution. Midnight is no longer included in the minimal wheel.

To enable the optional CPython fast path:

```python
app = Night().fast()
```

`app.fast()` uses `orjson` for dict/list responses. With `night run`, Night also selects `uvloop`, `httptools`, and `websockets` when installed. External ASGI servers still control their own backend selection.''',
)

prepend_after_title(
    'docs/ja/getting-started/quickstart.md',
    '### インストール構成（0.1.5）',
    '''### インストール構成（0.1.5）

依存なしの最小構成:

```bash
python -m pip install -U all-night
```

CPython向けの推奨構成（高速サーバースタック、Midnight、Cloudflareの型/ランタイム補助を含む）:

```bash
python -m pip install -U "all-night[standard]"
```

`standard` は `uvicorn[standard]`、`orjson`、Python 3.13+ では `workers-runtime-sdk`、さらに別配布の `all-night-midnight` を導入します。0.1.5からMidnightは最小wheelには同梱されません。

高速化を有効にするには:

```python
app = Night().fast()
```

`app.fast()` はdict/listレスポンスに `orjson` を使い、`night run` では利用可能なら `uvloop`、`httptools`、`websockets` も選択します。外部ASGIサーバーを直接使う場合、event loop/backendの選択権はそのサーバー側にあります。''',
)

prepend_after_title(
    'docs/guides/midnight.md',
    '## Installation in 0.1.5+',
    '''## Installation in 0.1.5+

Midnight is an optional standard-profile feature and is no longer bundled in the minimal `all-night` wheel.

```bash
python -m pip install -U "all-night[standard]"
```

The extra installs the separate `all-night-midnight` distribution, which provides `night_midnight`, `night_midnight_component`, `night_midnight_dev`, and `night_midnight_form`.''',
)

prepend_after_title(
    'docs/ja/guides/midnight.md',
    '## 0.1.5以降のインストール',
    '''## 0.1.5以降のインストール

Midnightは `standard` 構成のオプション機能になり、最小の `all-night` wheelには同梱されません。

```bash
python -m pip install -U "all-night[standard]"
```

このextraが別配布の `all-night-midnight` を導入し、`night_midnight`、`night_midnight_component`、`night_midnight_dev`、`night_midnight_form` を提供します。''',
)

prepend_after_title(
    'docs/guides/cloudflare-workers.md',
    '## Standard profile and Workers',
    '''## Standard profile and Workers

`all-night[standard]` includes `workers-runtime-sdk` on Python 3.13+ so local CPython development can share Cloudflare runtime types with the rest of the full Night stack. For deployment, Cloudflare Python Workers use Pyodide rather than Uvicorn, so `app.fast()`'s `uvloop`/`httptools` path is intentionally not used inside Workers.

A Workers project should keep the runtime dependency small and use Cloudflare's current toolchain:

```toml
[project]
dependencies = ["all-night==0.1.5"]

[dependency-groups]
dev = ["workers-py", "workers-runtime-sdk"]
```

Use `uv run pywrangler dev` and `uv run pywrangler deploy` for local development and deployment.''',
)

prepend_after_title(
    'docs/ja/guides/cloudflare-workers.md',
    '## standard構成とWorkers',
    '''## standard構成とWorkers

`all-night[standard]` はPython 3.13+で `workers-runtime-sdk` も導入するため、通常のCPython開発環境でもCloudflare runtimeの型を利用できます。一方、Cloudflare Python Workers本番環境はUvicornではなくPyodide上で動くため、`app.fast()` の `uvloop` / `httptools` 経路はWorkers内では使いません。

Workersプロジェクト側はランタイム依存を小さく保ち、Cloudflareの現行ツールチェーンを使います:

```toml
[project]
dependencies = ["all-night==0.1.5"]

[dependency-groups]
dev = ["workers-py", "workers-runtime-sdk"]
```

ローカル開発は `uv run pywrangler dev`、デプロイは `uv run pywrangler deploy` を使います。''',
)

append_once(
    'docs/reference/application.md',
    '## Fast mode',
    '''## Fast mode

`Night.fast()` enables the optional standard-profile CPython fast path and returns the same application instance, so `app = Night().fast()` is supported. It requires `all-night[standard]`; otherwise it raises a clear runtime error. Dict/list responses use `orjson`, and `night run` selects installed Uvicorn fast backends (`uvloop`, `httptools`, `websockets`).''',
)

append_once(
    'docs/ja/reference/application.md',
    '## Fast mode',
    '''## Fast mode

`Night.fast()` はstandard構成のCPython向け高速化を有効にし、同じアプリインスタンスを返すため `app = Night().fast()` と書けます。`all-night[standard]` が必要です。dict/listレスポンスでは `orjson` を使い、`night run` は導入済みの `uvloop`、`httptools`、`websockets` を選択します。''',
)

append_once(
    'docs/reference/tooling.md',
    '### Fast-mode server selection',
    '''### Fast-mode server selection

When the loaded application has `app.fast()` enabled, `night run` asks Uvicorn to use `uvloop`, `httptools`, and `websockets` when those modules are installed by `all-night[standard]`. Without fast mode, the existing Uvicorn defaults are preserved.''',
)

append_once(
    'docs/ja/reference/tooling.md',
    '### Fast mode時のサーバー選択',
    '''### Fast mode時のサーバー選択

読み込んだアプリで `app.fast()` が有効な場合、`night run` は `all-night[standard]` によって利用可能な `uvloop`、`httptools`、`websockets` をUvicornへ指定します。fast modeでなければ従来のUvicornデフォルトを維持します。''',
)
