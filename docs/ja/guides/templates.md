# テンプレート

Night は `night.py` 本体に、外部依存なしのテンプレートエンジンを持ちます。通常のCPythonを中心に動作しつつ、Midnightのような拡張が同じ描画基盤を継承できる設計です。

## ファイルテンプレート

`templates/index.html`:

```html
<h1>${{ title }}</h1>

${% if user.admin %}
  <strong>Admin</strong>
${% else %}
  <span>User</span>
${% endif %}

<ul>
${% for item in items %}
  <li>${{ loop.index }}. ${{ item }}</li>
${% else %}
  <li>項目なし</li>
${% endfor %}
</ul>
```

ルートからは `render_template()` で描画します。

```python
from night import Night, render_template

app = Night()

@app.get("/")
def home():
    return render_template(
        "index.html",
        title="Night",
        user={"admin": True},
        items=["one", "two"],
    )
```

`Night(template_folder="views")` でテンプレートディレクトリを変更できます。`render_template()` はrequest中なら、そのNightアプリの `TemplateEngine` を自動利用します。

## 文字列・テキストテンプレート

```python
from night import render_template_string, render_text_template

html = render_template_string(
    "<h1>${{ title }}</h1>",
    title="Night",
)

text = render_text_template(
    "Hello ${{ name }}",
    name="Ada",
)
```

`render_template()` / `render_template_string()` は `HTMLResponse` を返し、埋め込み値を標準でHTML escapeします。`render_text_template()` はHTML escapeなしの通常のPython文字列を返します。

## 構文

値の埋め込み:

```text
${{ user.name }}
${{ items[0] }}
${{ score + 1 }}
```

条件分岐:

```text
${% if score >= 90 %}
A
${% elif score >= 70 %}
B
${% else %}
C
${% endif %}
```

ループ:

```text
${% for key, value in data | items %}
${{ loop.index }}: ${{ key }} = ${{ value }}
${% endfor %}
```

include:

```text
${% include "header.html" %}
```

コメント:

```text
${# ここは描画されない #}
```

## フィルター

標準で `safe`, `upper`, `lower`, `length`, `items`, `json` を利用できます。

```html
<h1>${{ title | upper }}</h1>
<div>${{ trusted_html | safe }}</div>
```

独自filterも追加できます。

```python
@app.template_engine.filter("bang")
def bang(value):
    return f"{value}!"
```

## 制限付き式評価

テンプレート式をそのままPythonの `eval()` には渡しません。制限付きAST evaluatorを使い、変数、mapping/object属性、添字、比較、bool演算、基本的な四則演算、list/tuple/dict、条件式などを扱います。関数呼び出し、comprehension、lambda、private name / private attributeは拒否します。

ただしテンプレートsource自体を、信用できない第三者コードを安全実行するsandboxとして扱う設計ではありません。

## 拡張しやすい根幹

中心になるクラスは `Template` と `TemplateEngine` です。

```python
from night import Template, TemplateEngine
```

`TemplateEngine.compile()` が再利用可能な `Template` を作ります。拡張側は `TemplateEngine` を継承し、parser、if/for/include、cache、式評価を再実装せずに、contextや値の描画処理だけ差し替えられます。

```python
from night import TemplateEngine

class MyEngine(TemplateEngine):
    def render_value(self, expression, value, context, *, autoescape, options):
        value = super().render_value(
            expression,
            value,
            context,
            autoescape=autoescape,
            options=options,
        )
        return f"[{value}]"
```

Midnightも別のテンプレートparserを持たず、この拡張点を使います。

## Midnightとの連携

`MidnightTemplateEngine` は `TemplateEngine` のサブクラスです。通常のNightテンプレートにlive bindingを追加します。

```python
from night_midnight import midnight

page = midnight.render_template_string("""
<h1>${{ title }}</h1>
<p>${{ count }}</p>
""", title="Night", count=0)
```

生成HTMLには `data-midnight-bind` が入り、Python側からページ全体を再描画せず更新できます。

```python
midnight.set("count", 1)
```

IFやFORなど初期描画は通常のNightテンプレートエンジンが担当し、Midnightはその上に双方向更新だけを追加します。
