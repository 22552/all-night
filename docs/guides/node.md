# Node.js runtime

Night officially supports Node.js **22 and 24** through the Web-standard runtime adapter in `night_node.mjs`. Both Node lines run in CI.

The adapter hosts Night inside Pyodide and keeps the transport boundary outside the Python routing core:

```text
Node Request
  -> night_node.mjs
  -> Pyodide
  -> night_web.handle_web
  -> Night
  -> Web Response
```

## Requirements

- Node.js 22 or 24; the minimum supported major is 22.
- The repository pins the npm `pyodide` runtime used by this adapter.
- A source directory containing `night.py`, `night_web.py`, and `app.py`. `night_request_info.py` is loaded when present.

Install the Node runtime dependency from the repository root:

```bash
npm install
```

## Example

Create `python/app.py`:

```python
from night import Night

app = Night()
app.get("/", lambda: {"hello": "node"})
```

Then create a Fetch-style handler:

```js
import { createNightNodeHandler } from "./night_node.mjs";

const night = createNightNodeHandler({
  sourceDir: "python",
});

const response = await night(new Request("https://night.local/"));
console.log(response.status, await response.text());
```

`createNightNodeHandler()` accepts Web-standard `Request` objects and returns Web-standard `Response` objects, which makes it suitable for Node platforms that already expose Fetch APIs.

## Warm runtime behavior

The Pyodide interpreter and imported Night application are initialized once and reused by later requests in the same Node process. The JavaScript/Python globals bridge is serialized so concurrent requests cannot overwrite each other's request data while sharing that interpreter.

This means route registration and Python module initialization are normally paid once per warm process rather than once per request.

## Platform metadata

Use `platform` and `platformInfo` to pass trusted host metadata into Night's stable request-info state:

```js
const night = createNightNodeHandler({
  sourceDir: "python",
  platform: "my-node-host",
  platformInfo: (_context, request) => ({
    request_id: request.headers.get("x-request-id"),
  }),
});
```

## Current limits

The Node bridge currently buffers request and response bodies. Night WebSockets and streaming responses still require a runtime-specific streaming/socket bridge. Filesystem-dependent Python features also follow Pyodide's virtual filesystem rather than the host filesystem unless explicitly bridged.
