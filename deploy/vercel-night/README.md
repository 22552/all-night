# Night on Vercel

This directory is a minimal Night application for Vercel's Python runtime.
Vercel accepts an `app` variable that exposes an ASGI application, so Night does
not need a Vercel-specific request/response adapter.

## Deploy

Use this directory as the Vercel project root, then deploy with Git integration
or the Vercel CLI.

```bash
vercel
```

The `pyproject.toml` pins the Python project metadata and declares `app.py` as
the Vercel entrypoint. Night is installed from PyPI as `all-night`.

Routes in the example:

- `GET /`
- `GET /users/<int:user_id>`
- `GET /health`

For local ASGI development you can also run:

```bash
python -m pip install all-night uvicorn
uvicorn app:app --reload
```

Vercel's Python runtime supports ASGI applications and streaming responses. For
production projects, keep the function bundle small and use a supported Python
version declared in `pyproject.toml`.
