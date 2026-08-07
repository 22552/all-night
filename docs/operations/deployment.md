# Deployment

Night 0.1.1 supports Python 3.11+ and can be installed from PyPI with `pip install all-night`.

The repository includes a portable `Dockerfile`, `docker-compose.yml`, `render.yaml`, and a Cloudflare Python Workers template under `deploy/cloudflare-night`.

## ASGI servers

For a conventional Python deployment, run Night under an ASGI server such as Uvicorn or Hypercorn:

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

TLS termination and proxy configuration normally belong in the deployment layer. Ensure the ASGI `scheme` reflects the external request when secure session Cookies depend on it.

## Local container

```bash
docker compose up --build
curl http://localhost:8000/health
```

To deploy an application of your own, replace the example module target with `your_module:app`, or build from a project that installs `all-night` from PyPI.

## Render

1. Create a Render Blueprint from the repository or your application repository.
2. Render detects `render.yaml`, builds the container, and probes the configured health endpoint.
3. Pushes to the linked branch deploy the service.

## Railway

Create a project from the GitHub repository. Railway can build the root `Dockerfile`; the container should read the platform-provided `PORT`.

## Cloudflare Python Workers

Night can run directly inside Cloudflare Python Workers through `Night.cloudflare_fetch()` and `Night.cloudflare_rpc()`. See [Cloudflare Python Workers](../guides/cloudflare-workers.md) for the full setup.

Cloudflare Python Workers run through Pyodide in Workers isolates. During deployment, Cloudflare executes top-level module initialization and snapshots the initialized WebAssembly linear memory to reduce cold-start work. Keep deterministic application construction and route registration at module scope, but do not perform request-specific work or binding I/O there.

The repository's Cloudflare template is validated in CI. Its compatibility date is intentionally pinned; update it only after testing the corresponding Python/Pyodide runtime behavior.

## Production notes

Use a strong `secret_key` supplied through the environment when signed sessions, flash messages, or CSRF helpers are enabled. Choose a `max_body_size` appropriate for expected uploads.

Night's signed session data is stored in the client Cookie. Application globals and other in-memory state are process- or isolate-local. Use a shared external store when multiple workers/processes need consistent data.

For Cloudflare Workers, do not store per-request user state in module globals. A warm isolate can handle multiple requests over its lifetime.
