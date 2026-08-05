# Night on Cloudflare Python Workers

This example runs a Night application on Cloudflare Python Workers.

## Cloudflare authentication (Python is not required)

Wrangler authentication itself only needs Node.js/npm. From any directory, run:

```bash
npx wrangler@latest login
```

A browser window will open. Sign in to Cloudflare and approve Wrangler access.

Confirm that authentication worked:

```bash
npx wrangler@latest whoami
```

If your environment supports Wrangler's keyring option and you prefer credentials stored through the OS keyring, you can use:

```bash
npx wrangler@latest login --use-keyring
```

## Running the Python Worker

The Worker runtime is Python/Pyodide, so running or deploying this Python Worker uses Cloudflare's Python Workers tooling. This example includes a `pyproject.toml` for that environment.

With `uv` and a suitable Python installation available:

```bash
cd examples/cloudflare_worker
uv sync
uv run pywrangler dev
```

Then deploy the Worker with:

```bash
uv run pywrangler deploy
```

The Cloudflare login created by Wrangler is separate from installing Python: you can complete authentication first on a machine with only Node.js/npm, then set up the Python Worker tooling when you have a Python-capable environment.

## Routes

The example exposes:

- `GET /`
- `GET /hello/<name>`
- `POST /echo` with a JSON request body

The entry point is `src/entry.py`, and Worker configuration is in `wrangler.jsonc`.
