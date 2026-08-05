# Minimal Cloudflare Python Worker probe

This template intentionally contains **no Night framework code**. It exists only to test whether Cloudflare Python Workers can initialize Pyodide successfully through the same Deploy Button / Workers Builds path.

[![Deploy to Cloudflare](https://deploy.workers.cloudflare.com/button)](https://deploy.workers.cloudflare.com/?url=https://github.com/22552/all-night/tree/main/deploy/cloudflare-minimal)

Expected response after a successful deploy:

```text
Cloudflare Python Worker OK
```

If this minimal template fails with the same `Dynamic require of "fs" is not supported` error, the failure is below Night and points to the Cloudflare Python Workers / pywrangler / Workers Builds path rather than the framework.
