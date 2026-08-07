# Night in the Browser

Run a Night app entirely inside the browser with Pyodide.

## Files

- `index.html` boots Pyodide and bridges Web-style requests into Night through `night_web.handle_web`.
- `app.py` is the Night application you edit.

## Run locally

Serve this directory with any static HTTP server, for example:

```bash
python -m http.server 8000 -d deploy/browser-night
```

Then open `http://localhost:8000`.

Opening `index.html` directly with `file://` is not recommended because browsers restrict module and fetch access from local files.

## Example app

```python
from night import Night

app = Night()

@app.get("/")
def index():
    return {"hello": "browser"}
```

The demo downloads `night.py` and `night_web.py`, loads `app.py` into Pyodide's in-memory filesystem, and executes requests without a Python server.

This adapter currently buffers request and response bodies. Browser WebSockets and streaming responses are not yet bridged.
