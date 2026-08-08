# Midnight Forms

Midnight は `input`、`change`、`submit` イベントで、その要素に属する HTML form の現在値をイベント payload に snapshot として載せます。core では `event["form"]` として取得でき、拡張モジュール `night_midnight_form` を使うと読み取り専用の `FormSnapshot` として扱えます。

## 入力中のフォームを読む

```html
<form id="profile">
  <input name="user">
  <input name="email" type="email">
</form>
```

```python
from night_midnight import midnight
from night_midnight_form import form

@midnight.on("input", "#profile")
def editing(event):
    data = form(event)
    midnight.text("#preview", data.getone("user", ""))
```

`input` のたびに、その時点で browser の `FormData` に入る form controls が snapshot されます。`change` と `submit` も同じ形式です。

## データ形式

通常の field は文字列です。

```python
{"user": "Ada"}
```

同じ `name` が複数ある場合は list になります。

```html
<input type="checkbox" name="lang" value="python" checked>
<input type="checkbox" name="lang" value="rust" checked>
```

```python
{"lang": ["python", "rust"]}
```

`FormSnapshot` では両方を同じAPIで扱えます。

```python
data = form(event)

data.getone("user")       # "Ada"
data.getlist("user")      # ["Ada"]
data.getone("lang")       # 最初の値
data.getlist("lang")      # 全ての値
data.as_dict()             # 独立した mutable dict copy
```

`Mapping` を実装しているため、`data["user"]`、`"user" in data`、iteration、`len(data)` も使えます。

## submit

```python
@midnight.on("submit", "#signup", prevent_default=True)
async def signup(event):
    data = form(event)
    user = data.getone("user", "")
    email = data.getone("email", "")

    if not user or not email:
        midnight.text("#error", "必須項目を入力してください")
        return

    # 保存前には trusted server 側でも必ず再検証する。
    midnight.text("#status", "Ready")
```

`prevent_default=True` は通常の browser submit を止めるだけで、入力値を信頼できるようにする機能ではありません。event payload は常に client-controlled data として扱ってください。

## `input` / `change` / `submit`

`input` は live preview、検索欄、文字数表示、draft UI に向きます。`change` は確定した変更だけ欲しい場合、`submit` は最終送信に使います。

## Browser `FormData` のルール

Midnight は独自 form model を作らず、browser の `FormData` の挙動に合わせます。

- `name` のない control は snapshot に入らない;
- unchecked checkbox / radio は入らない;
- disabled control は入らない;
- 同名 field や multiple selection は list になることがある;
- 現在の bridge では値は文字列として届く。

数値、日付、bool、構造化データは Python 側で parse / validate してください。

## file input

現在の event snapshot は小さな serializable form state 用で、file transfer 用ではありません。`event["form"]` から file contents を取得する前提にはせず、Night の通常の multipart upload API など明示的な upload transport を使ってください。

## core payload と拡張

拡張モジュールは必須ではありません。従来どおり raw payload を読むコードも有効です。

```python
@midnight.on("input", "#profile")
def editing(event):
    raw = event.get("form") or {}
```

`night_midnight_form` は既存 payload を normalize し、`getone()` / `getlist()` を追加するだけです。browser protocol や core runtime dependency は増やしません。
