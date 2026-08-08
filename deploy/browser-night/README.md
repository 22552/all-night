# Night in the Browser

Run a Night app entirely inside the browser with Pyodide.

## Files

- `404.html` is the Browser Night shell and GitHub Pages SPA fallback. The Pages workflow also copies it to `index.html` so the project root loads with HTTP 200.
- `app.py` is the Night application loaded into Pyodide.
- `debug.html` is a small local request console.
- `sw.js` persistently caches versioned Pyodide CDN assets in Cache Storage.

The shell bridges Web-style requests into Night through `night_web.handle_web`.

## Pyodide cache

Browser Night registers `sw.js` before starting Pyodide. The worker uses the versioned cache `night-pyodide-v1` and cache-first handling only for `https://cdn.jsdelivr.net/pyodide/v*/full/*` requests. After a cold first load, Pyodide's JavaScript, WebAssembly, metadata, and loaded packages such as `sqlite3` can be reused by later visits.

Night source files and `app.py` are intentionally not pinned in that cache, so framework/application updates keep their normal behavior. Browser storage can still be evicted by the browser or cleared by the user.

## Run locally

```bash
python -m http.server 8000 -d deploy/browser-night
```

Open `http://localhost:8000/debug.html`.

Service workers require HTTP/HTTPS; `file://` does not support the persistent Pyodide cache.

## Example app

```python
from night import Night

app = Night()
app.get("/", lambda: {"hello": "browser"})
```

The browser adapter currently buffers request and response bodies. Browser WebSockets and streaming responses are not yet bridged.
