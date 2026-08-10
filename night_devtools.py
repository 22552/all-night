"""Development-only browser DevTools for Night applications."""

from __future__ import annotations

import collections
import datetime as dt
import itertools
import platform
import time
import traceback
import typing as t
import urllib.parse

from night import Blueprint, html as html_response, jsonify, request

__all__ = ["devtools_blueprint", "enable_devtools"]

_SENSITIVE_HEADERS = {
    "authorization",
    "cookie",
    "proxy-authorization",
    "set-cookie",
    "x-api-key",
    "x-auth-token",
}
_MAX_TRACEBACK_CHARS = 16_000


def _safe_headers(headers: t.Mapping[str, t.Any]) -> dict[str, t.Any]:
    safe: dict[str, t.Any] = {}
    for key, value in headers.items():
        normalized = str(key).lower()
        if normalized in _SENSITIVE_HEADERS or normalized.endswith(("-token", "-secret", "-api-key")):
            safe[str(key)] = "[redacted]"
        else:
            safe[str(key)] = value
    return safe


def _decode_headers(raw: t.Iterable[tuple[bytes, bytes]]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for key, value in raw:
        headers[key.decode("latin-1")] = value.decode("latin-1")
    return _safe_headers(headers)


def _decode_query(raw: bytes) -> dict[str, t.Any]:
    if not raw:
        return {}
    parsed = urllib.parse.parse_qs(raw.decode("latin-1"), keep_blank_values=True)
    return {key: values[0] if len(values) == 1 else values for key, values in parsed.items()}


def _iso_time(timestamp: float) -> str:
    return dt.datetime.fromtimestamp(timestamp, tz=dt.timezone.utc).isoformat(timespec="milliseconds")


def _format_client(client: t.Any) -> str | None:
    if client is None:
        return None
    if isinstance(client, (tuple, list)):
        return ":".join(str(part) for part in client)
    return str(client)


def _public_request(item: dict[str, t.Any], *, details: bool) -> dict[str, t.Any]:
    error = item["error"]
    result: dict[str, t.Any] = {
        "id": item["id"],
        "time": _iso_time(item["timestamp"]),
        "method": item["method"],
        "path": item["path"],
        "status": item["status"],
        "duration_ms": item["duration_ms"],
        "error": None if error is None else {"type": error["type"], "message": error["message"]},
    }
    if details:
        result.update(
            {
                "query": _decode_query(item["query_string"]),
                "client": _format_client(item["client"]),
                "scheme": item["scheme"],
                "http_version": item["http_version"],
                "headers": _decode_headers(item["raw_headers"]),
                "error": error,
            }
        )
    return result


def _route_data(app: t.Any) -> list[dict[str, t.Any]]:
    return [
        {
            "methods": sorted(route.methods),
            "path": route.raw_path,
            "name": route.name,
            "endpoint": getattr(route.endpoint, "__qualname__", repr(route.endpoint)),
            "module": getattr(route.endpoint, "__module__", None),
            "params": list(getattr(route, "param_names", ())),
            "dynamic": bool(getattr(route, "param_names", ())),
        }
        for route in app.routes
    ]


def _websocket_route_data(app: t.Any) -> list[dict[str, t.Any]]:
    return [
        {
            "path": route.raw_path,
            "name": route.name,
            "endpoint": getattr(route.endpoint, "__qualname__", repr(route.endpoint)),
            "module": getattr(route.endpoint, "__module__", None),
            "params": list(getattr(route, "param_names", ())),
        }
        for route in getattr(app, "websocket_routes", ())
    ]


def _find_request(app: t.Any, request_id: int) -> dict[str, t.Any] | None:
    for entry in getattr(app, "_night_devtools_requests", ()):
        if entry.get("id") == request_id:
            return entry
    return None


def _websocket_data(app: t.Any) -> dict[str, t.Any]:
    active = list(getattr(app, "_night_devtools_ws_active", {}).values())
    active.sort(key=lambda item: item["id"], reverse=True)
    recent = list(reversed(getattr(app, "_night_devtools_ws_recent", ())))
    return {"active": active, "recent": recent, "routes": _websocket_route_data(app)}


_DASHBOARD = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Night DevTools</title><style>
:root{color-scheme:dark;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;background:#0d1017;color:#dce4f2}*{box-sizing:border-box}body{margin:0;background:#0d1017;color:#dce4f2}header{padding:20px 28px;background:#151b27;border-bottom:1px solid #28344b;position:sticky;top:0;z-index:2}h1{font-size:21px;margin:0 0 5px}.muted{color:#9aabc6}.live{display:inline-block;width:8px;height:8px;border-radius:50%;background:#8ee6bd;margin-right:7px}main{padding:24px;max-width:1200px;margin:auto}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:12px;margin:18px 0 28px}.card,.panel{background:#151b27;border:1px solid #28344b;border-radius:10px}.card{padding:14px}.label{color:#9aabc6;font-size:12px}.value{font-size:18px;margin-top:6px}.panel{overflow:hidden;margin-bottom:22px}.panel-head{display:flex;gap:12px;align-items:center;justify-content:space-between;padding:13px 15px;border-bottom:1px solid #28344b}.panel-head h2{font-size:16px;margin:0}.panel-head input{width:min(360px,55vw);background:#0d1017;border:1px solid #34435f;border-radius:7px;padding:8px 10px;color:#dce4f2}table{width:100%;border-collapse:collapse}th,td{padding:10px 12px;text-align:left;border-bottom:1px solid #28344b;font-size:13px}th{color:#9aabc6;font-size:11px;text-transform:uppercase}tr:last-child td{border-bottom:0}tbody tr:hover{background:#192131}tbody tr.clickable{cursor:pointer}code{color:#8ee6bd}.method{color:#9fc9ff;font-weight:600}.ok,.ws-active{color:#8ee6bd}.warn{color:#ffd68a}.bad,.error{color:#ffb4ab}.latency{font-variant-numeric:tabular-nums}.empty{text-align:center;color:#7f90ad;padding:20px}.pill{display:inline-block;padding:2px 7px;border-radius:999px;background:#202b3d;color:#b8c8e4;font-size:11px}.drawer{position:fixed;top:0;right:0;width:min(620px,100vw);height:100vh;background:#111722;border-left:1px solid #34435f;z-index:10;transform:translateX(101%);transition:transform .16s;box-shadow:-18px 0 40px #0007;overflow:auto}.drawer.open{transform:translateX(0)}.drawer-head{position:sticky;top:0;background:#151b27;border-bottom:1px solid #28344b;padding:14px 16px;display:flex;justify-content:space-between;align-items:center}.drawer-head h2{font-size:16px;margin:0}.drawer button{background:#202b3d;border:1px solid #34435f;color:#dce4f2;border-radius:6px;padding:6px 10px}.drawer-body{padding:16px}.detail-grid{display:grid;grid-template-columns:130px 1fr;gap:8px 12px;margin-bottom:18px}.detail-grid .key,.section-title{color:#9aabc6}.drawer pre{background:#0b0f16;border:1px solid #28344b;border-radius:8px;padding:12px;white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}.section-title{font-size:12px;text-transform:uppercase;margin:18px 0 8px}@media(max-width:700px){main{padding:14px}.panel{overflow:auto}th,td{white-space:nowrap}header{padding:16px}.detail-grid{grid-template-columns:95px 1fr}}
</style></head><body><header><h1>Night DevTools</h1><div class="muted"><span class="live"></span>development-only live inspector</div></header><main><section class="cards" id="summary"></section>
<section class="panel"><div class="panel-head"><h2>Recent requests</h2><span class="muted">click for details</span></div><table><thead><tr><th>Method</th><th>Path</th><th>Status</th><th>Latency</th><th>Time</th><th>Error</th></tr></thead><tbody id="requests"><tr><td colspan="6" class="empty">No application requests yet</td></tr></tbody></table></section>
<section class="panel"><div class="panel-head"><h2>WebSockets</h2><span class="muted">active + recently closed</span></div><table><thead><tr><th>State</th><th>Path</th><th>Client</th><th>Duration</th><th>Close</th></tr></thead><tbody id="websockets"><tr><td colspan="5" class="empty">No WebSocket connections yet</td></tr></tbody></table></section>
<section class="panel"><div class="panel-head"><h2>Routes</h2><input id="route-filter" type="search" placeholder="Filter routes…"></div><table><thead><tr><th>Methods</th><th>Path</th><th>Name</th><th>Endpoint</th><th>Params</th></tr></thead><tbody id="routes"></tbody></table></section></main>
<aside class="drawer" id="drawer"><div class="drawer-head"><h2 id="drawer-title">Request</h2><button id="drawer-close">Close</button></div><div class="drawer-body" id="drawer-body"></div></aside><script>
const esc=v=>String(v==null?'':v).replace(/[&<>\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]));const base=location.pathname.replace(/\\/?$/,'/');let allRoutes=[];const api=p=>fetch(base+p,{headers:{accept:'application/json'}}).then(r=>{if(!r.ok)throw Error(r.status+' '+r.statusText);return r.json()});const sc=s=>s>=500?'bad':s>=400?'warn':'ok';
function routes(){const q=document.querySelector('#route-filter').value.trim().toLowerCase(),rows=allRoutes.filter(r=>!q||[r.methods.join(' '),r.path,r.name,r.endpoint,r.module].join(' ').toLowerCase().includes(q));document.querySelector('#routes').innerHTML=rows.length?rows.map(r=>`<tr><td class="method">${esc(r.methods.join(', '))}</td><td><code>${esc(r.path)}</code></td><td>${esc(r.name||'')}</td><td>${esc(r.endpoint||'')}<div class="muted">${esc(r.module||'')}</div></td><td>${(r.params||[]).map(p=>`<span class="pill">${esc(p)}</span>`).join(' ')||'—'}</td></tr>`).join(''):'<tr><td colspan="5" class="empty">No matching routes</td></tr>'}
function summary(){return api('api/summary').then(d=>{const v=[['HTTP routes',d.routes],['WS routes',d.websockets],['WS active',d.websocket_active],['Requests kept',d.requests],['Middleware',d.middlewares],['RPC methods',d.rpc_methods],['Python',d.python],['Fast mode',d.fast?'on':'off']];document.querySelector('#summary').innerHTML=v.map(x=>`<div class="card"><div class="label">${esc(x[0])}</div><div class="value">${esc(x[1])}</div></div>`).join('')})}
function requests(){return api('api/requests').then(d=>{const rows=d.requests||[];document.querySelector('#requests').innerHTML=rows.length?rows.map(x=>`<tr class="clickable" data-id="${esc(x.id)}"><td class="method">${esc(x.method)}</td><td><code>${esc(x.path)}</code></td><td class="${sc(x.status)}">${esc(x.status)}</td><td class="latency">${Number(x.duration_ms).toFixed(2)} ms</td><td>${esc(x.time)}</td><td class="bad">${esc(x.error?x.error.type+': '+x.error.message:'')}</td></tr>`).join(''):'<tr><td colspan="6" class="empty">No application requests yet</td></tr>';document.querySelectorAll('[data-id]').forEach(r=>r.onclick=()=>detail(r.dataset.id))})}
function websockets(){return api('api/websockets').then(d=>{const rows=[...(d.active||[]).map(x=>({...x,state:'active'})),...(d.recent||[]).slice(0,20).map(x=>({...x,state:'closed'}))];document.querySelector('#websockets').innerHTML=rows.length?rows.map(x=>`<tr><td class="${x.state==='active'?'ws-active':'muted'}">${x.state}</td><td><code>${esc(x.path)}</code></td><td>${esc(x.client||'—')}</td><td>${x.duration_ms==null?'open':Number(x.duration_ms).toFixed(1)+' ms'}</td><td>${esc(x.close_code==null?'—':x.close_code)}</td></tr>`).join(''):'<tr><td colspan="5" class="empty">No WebSocket connections yet</td></tr>'})}
function block(v){return '<pre>'+esc(JSON.stringify(v==null?{}:v,null,2))+'</pre>'}function detail(id){api('api/requests/'+encodeURIComponent(id)).then(x=>{document.querySelector('#drawer-title').textContent=x.method+' '+x.path;let b=`<div class="detail-grid"><div class="key">Status</div><div class="${sc(x.status)}">${x.status}</div><div class="key">Latency</div><div>${Number(x.duration_ms).toFixed(3)} ms</div><div class="key">Time</div><div>${esc(x.time)}</div><div class="key">Client</div><div>${esc(x.client||'—')}</div><div class="key">Scheme</div><div>${esc(x.scheme||'—')}</div><div class="key">HTTP</div><div>${esc(x.http_version||'—')}</div></div><div class="section-title">Query</div>${block(x.query)}<div class="section-title">Headers</div>${block(x.headers)}`;if(x.error)b+=`<div class="section-title bad">Exception</div><div class="bad">${esc(x.error.type+': '+x.error.message)}</div><pre>${esc(x.error.traceback||'')}</pre>`;document.querySelector('#drawer-body').innerHTML=b;document.querySelector('#drawer').classList.add('open')})}
document.querySelector('#drawer-close').onclick=()=>document.querySelector('#drawer').classList.remove('open');document.querySelector('#route-filter').oninput=routes;api('api/routes').then(d=>{allRoutes=d.routes;routes()});summary();requests();websockets();setInterval(()=>{requests();websockets()},1000);setInterval(summary,5000);
</script></body></html>"""


def devtools_blueprint(app: t.Any) -> Blueprint:
    tools = Blueprint("night_devtools", url_prefix="/__night__")

    @tools.get("/", name="night_devtools.index")
    def index():
        return html_response(_DASHBOARD)

    @tools.get("/api/routes", name="night_devtools.routes")
    def routes():
        return jsonify({"routes": _route_data(app)})

    @tools.get("/api/summary", name="night_devtools.summary")
    def summary():
        return jsonify({
            "debug": bool(getattr(app, "debug", False)),
            "routes": len(app.routes),
            "websockets": len(getattr(app, "websocket_routes", ())),
            "websocket_active": len(getattr(app, "_night_devtools_ws_active", {})),
            "requests": len(getattr(app, "_night_devtools_requests", ())),
            "middlewares": len(getattr(app, "middlewares", ())),
            "before_hooks": len(getattr(app, "before_hooks", ())),
            "after_hooks": len(getattr(app, "after_hooks", ())),
            "rpc_methods": len(getattr(app, "rpc_methods", {})),
            "extensions": len(getattr(app, "extensions", {})),
            "fast": bool(getattr(app, "_fast_mode", False)),
            "python": platform.python_version(),
            "runtime": platform.python_implementation(),
        })

    @tools.get("/api/requests", name="night_devtools.requests")
    def requests():
        return jsonify({"requests": [_public_request(item, details=False) for item in reversed(getattr(app, "_night_devtools_requests", ()))]})

    @tools.get("/api/requests/<int:request_id>", name="night_devtools.request_detail")
    def request_detail(request_id: int):
        item = _find_request(app, request_id)
        if item is None:
            return jsonify({"error": "Request trace not found"}, status=404)
        return jsonify(_public_request(item, details=True))

    @tools.get("/api/websockets", name="night_devtools.websockets")
    def websockets():
        return jsonify(_websocket_data(app))

    @tools.get("/api/request", name="night_devtools.request")
    def request_info():
        req = request()
        return jsonify({"method": req.method, "path": req.path, "query": req.query, "client": req.client, "headers": _safe_headers(dict(req.headers))})

    return tools


def enable_devtools(app: t.Any, *, url_prefix: str = "/__night__", request_history: int = 100, websocket_history: int = 50) -> Blueprint:
    """Mount the debug-only inspector with bounded in-memory traces.

    HTTP header/query decoding is deliberately deferred until the dashboard API
    is read, keeping application request tracing cheap. Bodies are never stored.
    """
    if not bool(getattr(app, "debug", False)):
        raise RuntimeError("Night DevTools requires Night(debug=True).")
    if getattr(app, "_night_devtools_enabled", False):
        raise RuntimeError("Night DevTools is already enabled for this application.")
    if int(request_history) <= 0:
        raise ValueError("request_history must be greater than zero")
    if int(websocket_history) <= 0:
        raise ValueError("websocket_history must be greater than zero")

    root_path = "/" + url_prefix.strip("/")
    app._night_devtools_requests = collections.deque(maxlen=int(request_history))
    app._night_devtools_request_ids = itertools.count(1)
    app._night_devtools_ws_active = {}
    app._night_devtools_ws_recent = collections.deque(maxlen=int(websocket_history))
    app._night_devtools_ws_ids = itertools.count(1)

    async def _request_trace(req, call_next):
        if req.path == root_path or req.path.startswith(root_path + "/"):
            return await call_next()
        started = time.perf_counter()
        status = 500
        error: dict[str, str] | None = None
        try:
            response = await call_next()
            status = int(response.status)
            return response
        except Exception as exc:
            status = int(getattr(exc, "status", 500))
            tb = traceback.format_exc()
            error = {"type": type(exc).__name__, "message": str(exc), "traceback": tb[-_MAX_TRACEBACK_CHARS:]}
            raise
        finally:
            scope = req.scope
            app._night_devtools_requests.append({
                "id": next(app._night_devtools_request_ids),
                "timestamp": time.time(),
                "method": req.method,
                "path": req.path,
                "status": status,
                "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                "query_string": scope.get("query_string", b""),
                "client": scope.get("client"),
                "scheme": scope.get("scheme"),
                "http_version": scope.get("http_version"),
                "raw_headers": tuple(scope.get("headers", ())),
                "error": error,
            })

    app.use(_request_trace)

    original_websocket_handler = app._handle_websocket

    async def _tracked_websocket(scope, receive, send):
        connection_id = next(app._night_devtools_ws_ids)
        started = time.perf_counter()
        entry = {
            "id": connection_id,
            "path": scope.get("path") or "/",
            "client": _format_client(scope.get("client")),
            "connected_at": _iso_time(time.time()),
            "accepted": False,
            "duration_ms": None,
            "close_code": None,
            "error": None,
        }
        app._night_devtools_ws_active[connection_id] = entry

        async def tracked_receive():
            event = await receive()
            if event.get("type") == "websocket.disconnect":
                entry["close_code"] = event.get("code")
            return event

        async def tracked_send(event):
            kind = event.get("type")
            if kind == "websocket.accept":
                entry["accepted"] = True
            elif kind == "websocket.close":
                entry["close_code"] = event.get("code")
            await send(event)

        try:
            return await original_websocket_handler(scope, tracked_receive, tracked_send)
        except Exception as exc:
            entry["error"] = {"type": type(exc).__name__, "message": str(exc)}
            raise
        finally:
            entry["duration_ms"] = round((time.perf_counter() - started) * 1000, 3)
            app._night_devtools_ws_active.pop(connection_id, None)
            app._night_devtools_ws_recent.append(dict(entry))

    app._handle_websocket = _tracked_websocket

    tools = devtools_blueprint(app)
    app.register_blueprint(tools, url_prefix=url_prefix)
    app.get(root_path, name="night_devtools.root")(tools.routes[0].endpoint)
    app._night_devtools_enabled = True
    return tools
