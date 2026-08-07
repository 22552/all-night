from night import Night, HTMLResponse

app = Night()


@app.get("/")
def index():
    return HTMLResponse(
        """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Browser Night</title>
  <style>
    :root{color-scheme:dark;--bg:#090b10;--panel:#121722;--panel2:#171d29;--line:#263044;--text:#f6f8fc;--muted:#9eabc0;--accent:#79c0ff;--accent2:#a78bfa}
    *{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(circle at 20% 0%,#18263b 0,transparent 38%),radial-gradient(circle at 100% 10%,#251a3d 0,transparent 33%),var(--bg);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
    .wrap{width:min(1000px,calc(100% - 32px));margin:auto;padding:64px 0 80px}.badge{display:inline-flex;gap:8px;align-items:center;padding:7px 11px;border:1px solid #ffffff18;border-radius:999px;background:#ffffff0b;color:#cbd5e1;font-size:13px}.dot{width:8px;height:8px;border-radius:50%;background:#63e6a6;box-shadow:0 0 16px #63e6a688}
    h1{font-size:clamp(44px,8vw,84px);line-height:.96;letter-spacing:-.055em;margin:24px 0 20px;max-width:820px}.grad{background:linear-gradient(90deg,var(--accent),#9ed8ff 40%,var(--accent2));-webkit-background-clip:text;background-clip:text;color:transparent}.lead{max-width:720px;color:var(--muted);font-size:clamp(17px,2.2vw,22px);line-height:1.55;margin:0 0 32px}
    .actions{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:50px}.btn{display:inline-flex;align-items:center;gap:8px;text-decoration:none;color:var(--text);padding:12px 16px;border-radius:12px;border:1px solid var(--line);background:var(--panel2);font-weight:700}.btn.primary{background:linear-gradient(135deg,#287fc1,#7352d8);border-color:transparent}.btn:hover{transform:translateY(-1px)}
    .grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}.card{padding:22px;border:1px solid var(--line);border-radius:18px;background:linear-gradient(180deg,#151b27dd,#10151fdd);box-shadow:0 18px 50px #0003}.card .icon{font-size:22px}.card h2{font-size:17px;margin:14px 0 8px}.card p{margin:0;color:var(--muted);line-height:1.55;font-size:14px}.code{margin-top:38px;padding:18px 20px;border:1px solid var(--line);border-radius:16px;background:#090d13;font:14px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace;color:#c5d3e5;overflow:auto}.code .k{color:#8cc8ff}.code .s{color:#9be4ae}.foot{margin-top:34px;color:#718096;font-size:13px}
    @media(max-width:760px){.wrap{padding-top:38px}.grid{grid-template-columns:1fr}h1{font-size:52px}}
  </style>
</head>
<body>
  <main class="wrap">
    <div class="badge"><span class="dot"></span> Night is live inside this browser</div>
    <h1>Python web apps,<br><span class="grad">without a server.</span></h1>
    <p class="lead">Browser Night runs the Night framework locally with Pyodide. Routes are handled by Python in this tab, while the surrounding browser shell stays warm for fast SPA navigation.</p>
    <div class="actions">
      <a class="btn primary" href="/all-night/hello/night">Try /hello/night →</a>
      <a class="btn" href="https://github.com/22552/all-night" target="_blank" rel="noreferrer">View Night on GitHub</a>
    </div>
    <section class="grid">
      <article class="card"><div class="icon">⚡</div><h2>Warm after first load</h2><p>Pyodide starts once. Route changes reuse the same Python runtime instead of cold-starting every page.</p></article>
      <article class="card"><div class="icon">🐍</div><h2>Real Night routes</h2><p>The same familiar Python decorators handle requests in-browser through the portable Web Request adapter.</p></article>
      <article class="card"><div class="icon">🌐</div><h2>Web-native shell</h2><p>HTML renders inside the app view, JSON stays plain and readable, and normal web resources can still use browser fetch.</p></article>
    </section>
    <div class="code"><span class="k">@app.get</span>(<span class="s">"/hello/&lt;name&gt;"</span>)<br>def hello(name: str):<br>&nbsp;&nbsp;&nbsp;&nbsp;return {<span class="s">"hello"</span>: name}</div>
    <div class="foot">Night · Browser/Pyodide deployment demo</div>
  </main>
</body>
</html>"""
    )


@app.get("/hello/<name>")
def hello(name: str):
    return {"hello": name}


@app.post("/echo")
async def echo(req):
    return {"received": await req.text()}
