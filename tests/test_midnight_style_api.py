from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).parent.parent


def test_midnight_style_api_is_exposed():
    script = (ROOT / "midnight.js").read_text()
    assert "style: setStyle" in script
    assert "show," in script
    assert "hide," in script
    assert "toggle," in script
    assert "css," in script
    assert "element.style.setProperty" in script
    assert "document.createElement(\"style\")" in script


def test_midnight_javascript_has_valid_syntax():
    node = shutil.which("node")
    if node is None:
        return
    subprocess.run([node, "--check", str(ROOT / "midnight.js")], check=True)
