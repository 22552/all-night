# Browser Night

Browser Night runs a Night application entirely inside a browser tab using Pyodide. The browser loads Python, writes Night and your `app.py` into Pyodide's in-memory filesystem, then sends Web-style requests through `night_web.handle_web` into the same Night routing core used on servers.

No Python HTTP server is required for the deployed demo.

## Files

- `deploy/browser-night/404.html` — the browser shell and SPA fallback. GitHub Pages copies it to `index.html` during deployment so `/all-night/` returns the shell normally while nested routes still fall back through `404.html`.
- `deploy/browser-night/app.py` — the application loaded into Pyodide.
- `deploy/browser-night/debug.html` — a small request/debug console useful for local development.
- `deploy/browser-night/sw.js` — persistent Pyodide runtime cache.
- `night_web.py` — the Web-style request/response adapter used inside Pyodide.

## Pyodide cache

Starting Pyodide is the expensive part of a cold browser load. Browser Night registers `sw.js` before starting the runtime. The service worker uses Cache Storage with a versioned cache name (`night-pyodide-v1`) and a cache-first strategy for requests under the versioned jsDelivr Pyodide paths.

This means assets such as `pyodide.mjs`, the WebAssembly runtime, package indexes, and loaded packages such as `sqlite3` can be reused on later visits. The first visit still needs the network. Browser storage may be evicted by the browser, and private/incognito modes may not preserve it.

Only versioned Pyodide CDN assets are cached by this service worker. Night's source files and `app.py` keep their normal update behavior, so updating the framework/application does not require clearing the large Pyodide cache. When the cache policy itself changes, bump the cache name in `sw.js`; activation deletes older `night-pyodide-*` caches.

## Application example

```python
from night import Night

app = Night()

@app.get("/")
def index():
    return {"hello": "browser"}
```

Fluent registration works too:

```python
app.get("/health", lambda: {"ok": True})
```

## Local debug page

From the browser demo directory:

```bash
python -m http.server 8000 -d deploy/browser-night
```

Open `http://localhost:8000/debug.html`. Service workers require HTTP/HTTPS (localhost is allowed); opening the files directly with `file://` cannot use the persistent runtime cache.

## Current limitations

The browser adapter currently buffers request and response bodies. WebSocket and streaming-response bridging are not yet implemented for Browser Night. Browser storage and network APIs also follow the browser's origin/CORS/security model rather than a normal server process.
