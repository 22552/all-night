# Deployment notes

Run Night under an ASGI server such as Uvicorn or Hypercorn. Put TLS termination and proxy configuration in the deployment layer, then ensure the ASGI `scheme` is correct so session Cookies receive the appropriate `Secure` attribute.

Use a strong, secret `secret_key` supplied through the environment. Set a body size appropriate to expected uploads and use explicit application-level authorization for protected endpoints.

The built-in session, rate-independent request handling, and any in-memory application state are process-local. For multi-process deployments, store shared state in an external service when consistency is required.


