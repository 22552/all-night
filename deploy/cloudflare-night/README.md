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

Todos are persisted in **Cloudflare Workers KV** through the `TODOS` binding. Each item is stored under a `todo:<uuid>` key, so the demo does not rely on isolate memory and does not need a shared numeric counter.

Wrangler automatic resource provisioning is used: the template declares the `TODOS` KV binding without an account-specific namespace ID. On deployment, Wrangler/Workers Builds can create and bind the KV namespace automatically.

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

Wrangler creates a local KV resource automatically for local development.

## Notes

- The template uses the `python_workers` compatibility flag.
- Night, the portable runtime adapter, and the Web runtime adapter are vendored into `src/` during the build.
- Workers KV is eventually consistent; this demo favors a simple edge-native persistence example over transactional semantics.
- Streaming/SSE and WebSockets are not part of this first portable Web adapter demo.
