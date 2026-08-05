# Deploy Night to Cloudflare

Deploy a small Night application to **Cloudflare Python Workers** from your browser.

[![Deploy to Cloudflare](https://deploy.workers.cloudflare.com/button)](https://deploy.workers.cloudflare.com/?url=https://github.com/22552/all-night/tree/main/deploy/cloudflare-night)

Click the button above, sign in to Cloudflare, choose the repository and Worker names, and let Workers Builds create and deploy the project.

## What gets deployed

The demo exposes:

- `GET /` — runtime information
- `GET /hello/<name>` — path parameter example
- `POST /echo` — echoes a JSON request body

The template is self-contained inside this directory so Cloudflare's subdirectory deploy flow can clone it as its own project.

## Build and deploy

Workers Builds reads `package.json` and uses:

```bash
python -m pip install uv && uv sync
uv run pywrangler deploy
```

Python packages are declared in `pyproject.toml`. The Night framework is pinned to a known repository commit so the template remains reproducible.

## Local development

If you have Python 3.13+, Node.js, and `uv` installed:

```bash
uv sync
uv run pywrangler dev
```

Then open the local Worker URL shown by Pywrangler.

## Notes

- Python Workers currently require the `python_workers` compatibility flag.
- Streaming/SSE and WebSockets are not part of this first portable adapter demo.
- The official Deploy to Cloudflare flow creates a copy of the template in your GitHub or GitLab account and configures Workers Builds for it.
