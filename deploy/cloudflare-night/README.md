# Deploy Night ToDo to Cloudflare

Deploy a small **Night ToDo application** to Cloudflare Python Workers from your browser.

[![Deploy to Cloudflare](https://deploy.workers.cloudflare.com/button)](https://deploy.workers.cloudflare.com/?url=https://github.com/22552/all-night/tree/main/deploy/cloudflare-night)

Click the button above, sign in to Cloudflare, choose the repository and Worker names, and let Workers Builds create and deploy the project.

## What gets deployed

The demo includes a browser UI and a JSON API:

- `GET /` — ToDo web UI
- `GET /api/todos` — list todos
- `POST /api/todos` — add a todo
- `PATCH /api/todos/<id>` — rename or toggle a todo
- `DELETE /api/todos/<id>` — delete a todo

Todos are intentionally stored in Worker memory for this runtime demo. They can disappear when the isolate is restarted; use D1, KV, Durable Objects, or another persistent store for a real application.

## Build and deploy

Workers Builds assembles the self-contained Python modules and deploys directly through Wrangler:

```bash
npm run build
npm run deploy
```

The deploy command is:

```bash
npx wrangler deploy
```

The template currently pins `compatibility_date` to `2025-12-01`. During testing, newer compatibility dates triggered a Cloudflare-side Pyodide initialization failure (`Dynamic require of "fs" is not supported`) even for a minimal Python Worker, while the older date deployed successfully.

## Local development

After running the build step, you can use Wrangler directly:

```bash
npm run build
npx wrangler dev
```

## Notes

- The template uses the `python_workers` compatibility flag.
- Night, the portable runtime adapter, and the Web runtime adapter are vendored into `src/` during the build.
- Streaming/SSE and WebSockets are not part of this first portable Web adapter demo.
