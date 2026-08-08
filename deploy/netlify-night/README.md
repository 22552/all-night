# Night on Netlify

This is the official Night template for Netlify Functions.

It runs Night under Node.js 24 using Pyodide and the repository's shared `night_node.mjs` Fetch adapter. Netlify's modern Web-standard `Request -> Response` function API means the platform-specific wrapper stays small.

## Run locally

```bash
npm install
npm run dev
```

`npm install` runs the template's `prepare` lifecycle, which vendors the current Night Python sources, your `python/app.py`, and the shared Node adapter into the function bundle.

## Deploy

When importing this repository into Netlify, set the base directory to:

```text
deploy/netlify-night
```

The included `netlify.toml` selects Node.js 24 and the Netlify Functions directory. The function itself owns the `/*` route through its modern `config.path` declaration.

For CLI deployment:

```bash
netlify link
netlify deploy
netlify deploy --prod
```

## Edit the application

Change `python/app.py`:

```python
from night import Night

app = Night()
app.get("/", lambda: {"hello": "netlify"})
```

## Runtime behavior

- Pyodide is initialized once per warm function instance.
- Night and the application are imported once per warm instance.
- Requests are serialized around the small shared Pyodide-globals bridge.
- Night source is bundled at build time; requests do not fetch framework code from GitHub or PyPI.
- Trusted Netlify context such as client IP and request ID is mapped into Night request info.

The current adapter buffers HTTP request and response bodies. WebSockets and streaming responses require a separate runtime bridge.
