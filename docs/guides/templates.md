# Templates

Night includes a dependency-free template engine in `night.py`. It is designed for normal CPython first, while keeping the rendering core subclassable by extensions such as Midnight.

## File templates

Create `templates/index.html`:

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
  <li>No items</li>
${% endfor %}
</ul>
```

Render it from a route:

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

`Night(template_folder="views")` changes the application template directory. `render_template()` automatically uses the active application's `TemplateEngine`.

## String and text templates

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

`render_template()` and `render_template_string()` return `HTMLResponse` and HTML-escape interpolated values by default. `render_text_template()` returns a plain Python string without HTML escaping.

## Syntax

Interpolation:

```text
${{ user.name }}
${{ items[0] }}
${{ score + 1 }}
```

Conditions:

```text
${% if score >= 90 %}
A
${% elif score >= 70 %}
B
${% else %}
C
${% endif %}
```

Loops:

```text
${% for key, value in data | items %}
${{ loop.index }}: ${{ key }} = ${{ value }}
${% endfor %}
```

Includes:

```text
${% include "header.html" %}
```

Comments:

```text
${# this is ignored #}
```

## Filters

Built-in filters include `safe`, `upper`, `lower`, `length`, `items`, and `json`.

```html
<h1>${{ title | upper }}</h1>
<div>${{ trusted_html | safe }}</div>
```

Custom filters are registered on an engine:

```python
@app.template_engine.filter("bang")
def bang(value):
    return f"{value}!"
```

## Restricted expressions

Night does not pass template expressions directly to Python `eval()`. Expressions are parsed through a restricted AST evaluator. Names, mapping/object attributes, subscripts, comparisons, boolean operators, basic arithmetic, lists/tuples/dicts, and conditional expressions are supported. Function calls, comprehensions, lambdas, and private names/attributes are rejected.

Templates are still application code, not a security sandbox for untrusted template source.

## Extension model

The core types are:

```python
from night import Template, TemplateEngine
```

`TemplateEngine.compile()` creates a reusable `Template`. Extensions can subclass `TemplateEngine`, override context/value rendering, and add filters while reusing the same parser, control-flow nodes, includes, cache, and restricted expression evaluator.

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

Midnight uses this extension point instead of implementing a second template parser.

## Midnight live bindings

Midnight's `MidnightTemplateEngine` extends `TemplateEngine`. Simple expressions become live DOM bindings:

```python
from night_midnight import midnight

page = midnight.render_template_string("""
<h1>${{ title }}</h1>
<p>${{ count }}</p>
""", title="Night", count=0)
```

The generated HTML contains `data-midnight-bind` markers. Python can update them without re-rendering the whole page:

```python
midnight.set("count", 1)
```

Control flow and initial rendering remain the normal Night template engine; Midnight adds the live-update layer on top.
