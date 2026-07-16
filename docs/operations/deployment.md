# Deployment

The repository includes a portable `Dockerfile`, `docker-compose.yml`, and `render.yaml`. The default container serves the example application defined as `night:app`.

## Local container

```bash
docker compose up --build
curl http://localhost:8000/health
```

To deploy an application of your own, replace `night:app` in the Dockerfile command with `your_module:app` (or build from a project that imports Night).

## Render

1. Create a Render Blueprint from this GitHub repository.
2. Render detects `render.yaml`, builds the Docker image, and probes `/health`.
3. Pushes to the linked branch automatically deploy the service.

## Railway

Create a project from the GitHub repository. Railway detects the root `Dockerfile`; set `PORT` only if your environment requires an explicit value. The container already reads the platform-provided `PORT`.

## Production notes

Run Night under an ASGI server such as Uvicorn or Hypercorn. Put TLS termination and proxy configuration in the deployment layer, then ensure the ASGI `scheme` is correct so session Cookies receive the appropriate `Secure` attribute.

Use a strong, secret `secret_key` supplied through the environment. Set a body size appropriate to expected uploads and use explicit application-level authorization for protected endpoints.

The built-in session and any in-memory application state are process-local. For multi-process deployments, store shared state in an external service when consistency is required.

