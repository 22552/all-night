import { readFile } from "node:fs/promises";
import { loadPyodide } from "pyodide";

let runtimePromise: Promise<any> | undefined;
let requestQueue: Promise<any> = Promise.resolve();

async function initRuntime() {
  if (runtimePromise) return runtimePromise;

  runtimePromise = (async () => {
    const pyodide = await loadPyodide();
    pyodide.FS.mkdirTree("/night");

    for (const name of ["night.py", "night_web.py", "app.py"]) {
      const source = await readFile(new URL(`./_python/${name}`, import.meta.url), "utf8");
      pyodide.FS.writeFile(`/night/${name}`, source, { encoding: "utf8" });
    }

    await pyodide.runPythonAsync(`
import sys
sys.path.insert(0, "/night")
from app import app
from night_web import handle_web
`);
    return pyodide;
  })();

  return runtimePromise;
}

async function execute(req: Request): Promise<Response> {
  const pyodide = await initRuntime();
  const method = req.method.toUpperCase();
  const body = method === "GET" || method === "HEAD"
    ? []
    : Array.from(new Uint8Array(await req.arrayBuffer()));
  const headers = Array.from(req.headers.entries());

  pyodide.globals.set("_night_method", method);
  pyodide.globals.set("_night_url", req.url);
  pyodide.globals.set("_night_headers", headers);
  pyodide.globals.set("_night_body", body);

  const result = await pyodide.runPythonAsync(`
_result = await handle_web(
    app,
    method=_night_method,
    url=_night_url,
    headers=_night_headers.to_py(),
    body=bytes(_night_body.to_py()),
)
_result.as_tuple()
`);

  const [status, responseHeaders, responseBody] = result.toJs({ create_proxies: false });
  result.destroy?.();

  return new Response(responseBody, {
    status: Number(status),
    headers: responseHeaders,
  });
}

export default async (req: Request) => {
  // Pyodide globals are shared by a warm Function instance. Serialize the
  // small bridge section so concurrent invocations cannot overwrite them.
  const task = requestQueue.then(() => execute(req), () => execute(req));
  requestQueue = task.then(() => undefined, () => undefined);
  return task;
};

export const config = {};
