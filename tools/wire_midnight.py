from pathlib import Path
import re


def replace_once(path, old, new):
    p = Path(path)
    text = p.read_text()
    if old not in text:
        if new in text:
            return
        raise SystemExit(f"missing block in {path}: {old[:80]!r}")
    p.write_text(text.replace(old, new, 1))


replace_once(
    "pyproject.toml",
    'py-modules = ["night", "night_mcp", "night_web", "night_request_info", "night_cloudflare"]',
    'py-modules = ["night", "night_mcp", "night_web", "night_request_info", "night_cloudflare", "night_midnight"]',
)

browser = Path("deploy/browser-night/404.html")
text = browser.read_text()
text = text.replace(
    "let pyodide=null,publicIp=null,currentVersion='',ready=false,settingSrcdoc=false;",
    "let pyodide=null,publicIp=null,currentVersion='',ready=false,settingSrcdoc=false,midnightFrameReady=false,midnightDispatch=null,midnightDispatchWs=null,midnightDrain=null,midnightSubscriptions=[];",
    1,
)

boot_pattern = re.compile(r"async function boot\(\)\{.*?\}\nasync function nightFetch", re.S)
boot = '''globalThis.nightMidnightPush=raw=>{if(!midnightFrameReady||!frame.contentWindow)return false;try{const command=JSON.parse(String(raw));frame.contentWindow.postMessage({type:'midnight-command',command},'*');return true}catch{return false}};
async function boot(){const cacheReady=await enablePyodideCache();setStatus(cacheReady?'Pyodide cache ready…':'Loading Pyodide…');pyodide=await loadPy();setStatus('Loading sqlite3…');setProgress(38);await pyodide.loadPackage('sqlite3');setStatus('Loading Night…');setProgress(58);pyodide.FS.mkdirTree('/night');const[night,web,info,midnight,app]=await Promise.all([text('https://raw.githubusercontent.com/22552/all-night/main/night.py'),text('https://raw.githubusercontent.com/22552/all-night/main/night_web.py'),text('https://raw.githubusercontent.com/22552/all-night/main/night_request_info.py'),text('https://raw.githubusercontent.com/22552/all-night/main/night_midnight.py'),text(new URL('app.py',ASSET_BASE))]);pyodide.FS.writeFile('/night/night.py',night);pyodide.FS.writeFile('/night/night_web.py',web);pyodide.FS.writeFile('/night/night_request_info.py',info);pyodide.FS.writeFile('/night/night_midnight.py',midnight);pyodide.FS.writeFile('/night/app.py',app);setProgress(78);await pyodide.runPythonAsync(`import sys\nsys.path.insert(0,'/night')\nfrom app import app\nfrom night_web import handle_web\nfrom night_midnight import midnight as _midnight\nasync def _midnight_dispatch_json(payload):\n    return await _midnight.dispatch_json(str(payload))\nasync def _midnight_dispatch_ws_json(payload):\n    return await _midnight.dispatch_ws_json(str(payload))\ndef _midnight_drain_json():\n    return _midnight.drain_json()`);midnightDispatch=pyodide.globals.get('_midnight_dispatch_json');midnightDispatchWs=pyodide.globals.get('_midnight_dispatch_ws_json');midnightDrain=pyodide.globals.get('_midnight_drain_json');midnightSubscriptions=JSON.parse(String(pyodide.runPython('_midnight.subscriptions_json()')));publicIp=await stun();ready=true;runtimeEl.textContent=`Pyodide ${currentVersion} · warm`;setProgress(100);overlay.classList.add('hidden')}
async function nightFetch'''
text, count = boot_pattern.subn(boot, text, count=1)
if count != 1:
    if "night_midnight.py" not in text:
        raise SystemExit("could not replace Browser Night boot")

needle = "const PROJECT_BASE=${JSON.stringify(PROJECT_BASE)};let seq=0;"
replacement = "const PROJECT_BASE=${JSON.stringify(PROJECT_BASE)};const midnightScript=document.createElement('script');midnightScript.src=PROJECT_BASE+'/midnight.js';document.head.appendChild(midnightScript);let seq=0;"
if needle in text:
    text = text.replace(needle, replacement, 1)
elif replacement not in text:
    raise SystemExit("could not inject midnight.js")

text = text.replace(
    "settingSrcdoc=true;frame.srcdoc=renderDocument(r.body,type);",
    "midnightFrameReady=false;settingSrcdoc=true;frame.srcdoc=renderDocument(r.body,type);",
    1,
)

if "async function runMidnight(" not in text:
    start = text.find("frame.addEventListener('load',()=>")
    end = text.find("document.querySelector('#nav-form')", start)
    if start < 0 or end < 0:
        raise SystemExit("could not locate Browser Night message bridge")
    frame_and_messages = '''frame.addEventListener('load',()=>{if(settingSrcdoc){settingSrcdoc=false;return}try{const href=frame.contentWindow.location.href;if(!href||href==='about:srcdoc'||href==='about:blank')return;const u=new URL(href);if(u.origin===location.origin&&(u.pathname===PROJECT_BASE||u.pathname.startsWith(PROJECT_BASE+'/'))){let path=u.pathname.slice(PROJECT_BASE.length)||'/';path+=u.search;try{frame.contentWindow.stop()}catch{};dispatch(path,{push:true})}}catch{}});
async function runMidnight(dispatcher,payload,target){if(!dispatcher)return;const raw=await dispatcher(JSON.stringify(payload||{}));const commands=JSON.parse(String(raw||'[]'));for(const command of commands)target?.postMessage({type:'midnight-command',command},'*')}
function flushMidnight(target){if(!midnightDrain)return;const commands=JSON.parse(String(midnightDrain()||'[]'));for(const command of commands)target?.postMessage({type:'midnight-command',command},'*')}
window.addEventListener('message',async e=>{const m=e.data;if(!m)return;if(m.type==='night-fetch'){try{const u=new URL(m.url,location.href);let path=u.pathname.startsWith(PROJECT_BASE)?u.pathname.slice(PROJECT_BASE.length)||'/':u.pathname;path+=u.search;const r=await nightFetch(path,m.method,m.headers,m.body);e.source?.postMessage({type:'night-fetch-result',id:m.id,status:r.status,headers:r.headers,body:Array.from(r.body)},'*')}catch(err){e.source?.postMessage({type:'night-fetch-result',id:m.id,status:500,headers:[['content-type','text/plain']],body:Array.from(new TextEncoder().encode(String(err)))},'*')}}else if(m.type==='night-navigate'){const u=new URL(m.url,location.href);let path=u.pathname.slice(PROJECT_BASE.length)||'/';path+=u.search;dispatch(path,{push:true})}else if(m.type==='midnight-ready'){midnightFrameReady=true;e.source?.postMessage({type:'midnight-config',subscriptions:midnightSubscriptions},'*');flushMidnight(e.source)}else if(m.type==='midnight-event'){await runMidnight(midnightDispatch,m.event,e.source)}else if(m.type==='midnight-ws'){await runMidnight(midnightDispatchWs,m.event,e.source)}});
'''
    text = text[:start] + frame_and_messages + text[end:]

browser.write_text(text)

app = Path("deploy/browser-night/app.py")
app_text = app.read_text()
if "from night_midnight import midnight" not in app_text:
    app_text = app_text.replace(
        "from night import Night, HTMLResponse\n\napp = Night()",
        "from night import Night, HTMLResponse\nfrom night_midnight import midnight\n\napp = Night()\n_midnight_count = 0\n\n\n@midnight.on('click', '#midnight-button')\ndef midnight_click(event):\n    global _midnight_count\n    _midnight_count += 1\n    midnight.text('#midnight-status', f'Python received {_midnight_count} click(s)')\n    midnight.emit('counter', {'count': _midnight_count})",
        1,
    )
    app_text = app_text.replace(
        ".card p{margin:0;color:var(--muted);line-height:1.55;font-size:14px}",
        ".card p{margin:0;color:var(--muted);line-height:1.55;font-size:14px}.mini{margin-top:14px;border:1px solid var(--line);background:#20293a;color:var(--text);border-radius:10px;padding:9px 12px;font-weight:700;cursor:pointer}.live{margin-top:10px!important;color:#9be4ae!important}",
        1,
    )
    app_text = app_text.replace(
        '<article class="card"><div class="icon">🌐</div><h2>Web-native shell</h2><p>HTML renders inside the app view, JSON stays plain and readable, and normal web resources can still use browser fetch.</p></article>',
        '<article class="card"><div class="icon">🌐</div><h2>Web-native shell</h2><p>HTML renders inside the app view, JSON stays plain and readable, and normal web resources can still use browser fetch.</p></article>\n      <article class="card"><div class="icon">🌙</div><h2>Midnight bridge</h2><p>DOM events can call Python directly, and Python can update this HTML without a server round trip.</p><button id="midnight-button" class="mini">Python +1</button><p id="midnight-status" class="live">Waiting for a click…</p></article>',
        1,
    )
    app_text = app_text.replace(
        '<div class="foot">Night · Browser/Pyodide deployment demo</div>',
        '<div class="foot">Night · Browser/Pyodide deployment demo · Midnight enabled</div>\n    <script>window.addEventListener("midnight:counter",e=>console.log("Midnight counter",e.detail))</script>',
        1,
    )
app.write_text(app_text)

for path, marker, line in [
    ("docs/README.md", "- [Browser Night]", "- [Midnight: Python ↔ HTML bridge](guides/midnight.md)\n"),
    ("docs/ja/README.md", "- [Browser Night]", "- [Midnight: Python ↔ HTML ブリッジ](guides/midnight.md)\n"),
]:
    p = Path(path)
    d = p.read_text()
    if "guides/midnight.md" not in d:
        pos = d.find(marker)
        if pos >= 0:
            d = d[:pos] + line + d[pos:]
        else:
            d += "\n" + line
        p.write_text(d)

readme = Path("README.md")
r = readme.read_text()
if "## Midnight" not in r:
    anchor = "## Browser Night"
    block = "## Midnight\n\nBrowser Night includes **Midnight**, a bidirectional Python ↔ HTML bridge for DOM events, structured DOM updates, custom events, and optional WebSocket transport. See `docs/guides/midnight.md`.\n\n"
    pos = r.find(anchor)
    r = r[:pos] + block + r[pos:] if pos >= 0 else r + "\n\n" + block
    readme.write_text(r)
