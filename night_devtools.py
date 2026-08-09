"""Development-only browser DevTools for Night applications."""

from __future__ import annotations

import platform
import typing as t

from night import Blueprint, html as html_response, jsonify, request

__all__ = ["devtools_blueprint", "enable_devtools"]


def _route_data(app: t.Any) -> list[dict[str, t.Any]]:
    return [
        {
            "methods": sorted(route.methods),
            "path": route.raw_path,
            "name": route.name,
            "endpoint": getattr(route.endpoint, "__qualname__", repr(route.endpoint)),
            "module": getattr(route.endpoint, "__module__", None),
        }
        for route in app.routes
    ]


def devtools_blueprint(app: t.Any) -> Blueprint:
    """Create the standalone Night DevTools Blueprint."""

    tools = Blueprint("night_devtools", url_prefix="/__night__")

    @tools.get("/", name="night_devtools.index")
    def index():
        return html_response("""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Night DevTools</title><style>
:root{color-scheme:dark;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}body{margin:0;background:#0d1017;color:#dce4f2}header{padding:22px 28px;background:#151b27;border-bottom:1px solid #28344b}h1{font-size:21px;margin:0 0 5px}.muted{color:#9aabc6}main{padding:26px;max-width:1100px;margin:auto}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:20px 0}.card,table{background:#151b27;border:1px solid #28344b;border-radius:8px}.card{padding:14px}.label{color:#9aabc6;font-size:12px}.value{font-size:18px;margin-top:6px}table{width:100%;border-collapse:separate;border-spacing:0;overflow:hidden}th,td{padding:10px 12px;text-align:left;border-bottom:1px solid #28344b}th{color:#9aabc6;font-size:12px}tr:last-child td{border-bottom:0}code{color:#8ee6bd}.method{color:#9fc9ff}.error{color:#ffb4ab}</style></head><body>
<header><h1>Night DevTools</h1><div class="muted">Development-only application inspector</div></header>
<main><section class="cards" id="summary"></section><h2>Routes</h2><table><thead><tr><th>Methods</th><th>Path</th><th>Name</th><th>Endpoint</th></tr></thead><tbody id="routes"></tbody></table></main>
<script>
const escape = value => String(value == null ? "" : value).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
fetch("./api/summary").then(r => r.json()).then(data => {
 document.querySelector("#summary").innerHTML = [["HTTP routes",data.routes],["WebSocket routes",data.websockets],["Python",data.python],["Runtime",data.runtime]].map(pair => '<div class="card"><div class="label">'+escape(pair[0])+'</div><div class="value">'+escape(pair[1])+'</div></div>').join("");
});
fetch("./api/routes").then(r => r.json()).then(data => {
 document.querySelector("#routes").innerHTML = data.routes.map(route => '<tr><td class="method">'+escape(route.methods.join(", "))+'</td><td><code>'+escape(route.path)+'</code></td><td>'+escape(route.name || "")+'</td><td>'+escape(route.endpoint || "")+'</td></tr>').join("");
}).catch(error => { document.querySelector("#routes").innerHTML = '<tr><td colspan="4" class="error">'+escape(error)+'</td></tr>'; });
</script></body></html>""")

    @tools.get("/api/routes", name="night_devtools.routes")
    def routes():
        return jsonify({"routes": _route_data(app)})

    @tools.get("/api/summary", name="night_devtools.summary")
    def summary():
        return jsonify({"debug": bool(getattr(app, "debug", False)), "routes": len(app.routes), "websockets": len(getattr(app, "websocket_routes", ())), "python": platform.python_version(), "runtime": platform.python_implementation()})

    @tools.get("/api/request", name="night_devtools.request")
    def request_info():
        req = request()
        return jsonify({"method": req.method, "path": req.path, "query": req.query, "client": req.client, "headers": dict(req.headers)})

    return tools


def enable_devtools(app: t.Any, *, url_prefix: str = "/__night__") -> Blueprint:
    """Mount DevTools on a debug-only Night application."""
    if not bool(getattr(app, "debug", False)):
        raise RuntimeError("Night DevTools requires Night(debug=True).")
    if getattr(app, "_night_devtools_enabled", False):
        raise RuntimeError("Night DevTools is already enabled for this application.")
    tools = devtools_blueprint(app)
    app.register_blueprint(tools, url_prefix=url_prefix)
    app._night_devtools_enabled = True
    return tools
