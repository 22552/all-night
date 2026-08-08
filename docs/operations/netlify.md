# Netlify Functions

Night officially supports **Netlify Functions on Node.js 24** through the shared Node/Pyodide adapter. The ready-to-copy template lives in [`deploy/netlify-night`](../../deploy/netlify-night).

Netlify Functions use Web-standard `Request` and `Response` objects, so the platform wrapper stays deliberately small:

```ts
import type { Config, Context } from "@netlify/functions";
import { createNightNodeHandler } from "./_shared/night_node.mjs";

const night = createNightNodeHandler({
  sourceDir: new URL("./_python/", import.meta.url),
  platform: "netlify",
});

export default (request: Request, context: Context) => night(request, context);

export const config: Config = {
  path: "/*",
};
```

There is no legacy Lambda-style `exports.handler` adapter in the supported template.

## How the template is built

`npm run prepare` vendors the current repository copies of:

- `night.py`
- `night_web.py`
- `night_request_info.py`
- your `python/app.py`
- `night_node.mjs`

into the Netlify Functions bundle. The function therefore does not download Night from GitHub or PyPI at request time.

`pyodide` remains an external Node module handled by Netlify's function bundler. A warm function instance reuses its initialized Pyodide runtime and Night application.

## Run locally

From the template directory:

```bash
cd deploy/netlify-night
npm install
npm run dev
```

The template pins Node 24 in `netlify.toml`. Night's generic Node adapter is also tested on Node 22, but the official Netlify template follows Netlify's current Node 24 runtime.

## Deploy

For a Git-backed Netlify site, use `deploy/netlify-night` as the base directory. Netlify will run the configured build command and expose the Night function on `/*`.

With the Netlify CLI you can also link and deploy the directory directly:

```bash
cd deploy/netlify-night
netlify link
netlify deploy
netlify deploy --prod
```

Use Netlify environment variables for secrets; do not commit secrets into `netlify.toml`.

## Netlify request metadata

The wrapper maps trusted Netlify `Context` data into Night request info when available, including client IP, request ID, country, city, timezone, latitude, and longitude.

## Current limits

The Node/Pyodide bridge buffers request and response bodies. WebSocket and streaming-response support are not currently bridged through the Netlify adapter. Cold starts also include Pyodide initialization, so this runtime favors portability over native-JavaScript startup size.
