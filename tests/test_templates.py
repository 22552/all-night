from pathlib import Path

import pytest

from night import (
    Night,
    SafeString,
    TemplateEngine,
    TemplateError,
    render_template,
    render_template_string,
    render_text_template,
)
from night_midnight import Midnight, MidnightTemplateEngine


def test_template_interpolation_and_html_escape():
    engine = TemplateEngine()
    assert engine.render_text("Hello ${{ name }}", name="Night") == "Hello Night"
    assert engine.render_text("${{ html }}", html="<b>x</b>", autoescape=True) == "&lt;b&gt;x&lt;/b&gt;"
    assert engine.render_text("${{ html | safe }}", html="<b>x</b>", autoescape=True) == "<b>x</b>"
    assert engine.render_text("${{ user.name }}", user={"name": "Ada"}) == "Ada"


def test_template_if_elif_else():
    engine = TemplateEngine()
    source = "${% if score >= 90 %}A${% elif score >= 70 %}B${% else %}C${% endif %}"
    assert engine.render_text(source, score=95) == "A"
    assert engine.render_text(source, score=80) == "B"
    assert engine.render_text(source, score=30) == "C"


def test_template_for_loop_and_loop_metadata():
    engine = TemplateEngine()
    source = "${% for item in items %}${{ loop.index }}:${{ item }};${% else %}empty${% endfor %}"
    assert engine.render_text(source, items=["a", "b"]) == "1:a;2:b;"
    assert engine.render_text(source, items=[]) == "empty"


def test_template_for_unpack_and_filters():
    engine = TemplateEngine()
    source = "${% for key, value in data | items %}${{ key }}=${{ value }};${% endfor %}"
    assert engine.render_text(source, data={"a": 1, "b": 2}) == "a=1;b=2;"
    assert engine.render_text("${{ name | upper }}", name="night") == "NIGHT"
    assert engine.render_text("${{ values | length }}", values=[1, 2, 3]) == "3"


def test_template_include_and_cache_refresh(tmp_path: Path):
    (tmp_path / "partial.html").write_text("<b>${{ value }}</b>")
    (tmp_path / "page.html").write_text('A${% include "partial.html" %}Z')
    engine = TemplateEngine(str(tmp_path))
    assert engine.render_file("page.html", value="x", autoescape=True) == "A<b>x</b>Z"

    (tmp_path / "partial.html").write_text("<i>${{ value }}</i>")
    assert engine.render_file("page.html", value="y", autoescape=True) == "A<i>y</i>Z"


def test_template_file_path_is_confined(tmp_path: Path):
    engine = TemplateEngine(str(tmp_path))
    with pytest.raises(TemplateError):
        engine.render_file("../outside.html")


def test_template_restricted_expression_language():
    engine = TemplateEngine()
    with pytest.raises(TemplateError):
        engine.render_text("${{ __import__('os').getcwd() }}")
    with pytest.raises(TemplateError):
        engine.render_text("${{ thing.__class__ }}", thing=object())


def test_template_custom_filter_and_subclass_hook():
    class WrappedEngine(TemplateEngine):
        def render_value(self, expression, value, context, *, autoescape, options):
            rendered = super().render_value(expression, value, context, autoescape=autoescape, options=options)
            return f"[{rendered}]"

    engine = WrappedEngine()

    @engine.filter("bang")
    def bang(value):
        return f"{value}!"

    assert engine.render_text("${{ name | bang }}", name="Night") == "[Night!]"


def test_render_helpers():
    response = render_template_string("<h1>${{ title }}</h1>", title="Night")
    assert response.body == b"<h1>Night</h1>"
    assert response.headers["content-type"].startswith("text/html")
    assert render_text_template("Hello ${{ name }}", name="Night") == "Hello Night"


def test_render_template_uses_active_app_engine(tmp_path: Path):
    (tmp_path / "index.html").write_text("<h1>${{ title }}</h1>")
    app = Night(template_folder=str(tmp_path))

    @app.get("/")
    def home():
        return render_template("index.html", title="Night")

    response = app.test_client().get("/")
    assert response.status_code == 200
    assert response.text == "<h1>Night</h1>"


def test_midnight_template_engine_live_bindings():
    engine = MidnightTemplateEngine()
    html = engine.render_text(
        "<h1>${{ title }}</h1><p>${{ count }}</p>",
        {"title": "Night", "count": 0},
        autoescape=True,
        render_options={"live": True},
    )
    assert 'data-midnight-bind="title"' in html
    assert 'data-midnight-bind="count"' in html


def test_midnight_render_and_set_command():
    bridge = Midnight()
    response = bridge.render_template_string("<p>${{ count }}</p>", count=1)
    assert b'data-midnight-bind="count"' in response.body

    bridge.set("count", 2)
    assert bridge.state["count"] == 2
    assert bridge.drain() == [{"op": "bind", "name": "count", "value": 2}]
