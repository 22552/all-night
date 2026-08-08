import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { loadPyodide } from "pyodide";

export const NIGHT_NODE_SUPPORT = Object.freeze({
  node: ">=22",
  tested: [22, 24],
  pyodide: "314.0.3",
});

function assertSupportedNode() {
  const major = Number.parseInt(process.versions.node.split(".", 1)[0], 10);
  if (!Number.isFinite(major) || major < 22) {
    throw new Error(`Night's Node runtime requires Node.js 22+; got ${process.versions.node}`);
  }
}

function sourceLocation(sourceDir, name) {
  if (sourceDir instanceof URL) return new URL(name, sourceDir);
  return resolve(String(sourceDir), name);
}

function toPlainPlatformInfo(value) {
  if (!value) return {};
  const out = {};
  for (const [key, item] of Object.entries(value)) {
    if (item == null) continue;
    if (["string", "number", "boolean"].includes(typeof item)) out[key] = item;
  }
  return out;
}

function responseHeadersFromPairs(pairs) {
  const headers = new Headers();
  for (const [key, value] of pairs ?? []) headers.append(String(key), String(value));
  return headers;
}

/**
 * Create a Fetch-compatible Night handler for Node.js.
 *
 * `sourceDir` must contain `night.py`, `night_web.py`, and `app.py`.
 * `night_request_info.py` is copied when present. The Pyodide interpreter is
 * initialized once per warm Node process and requests are serialized around
 * the small JS/Python globals bridge so concurrent invocations cannot race.
 */
export function createNightNodeHandler(options = {}) {
  const {
    sourceDir = "python",
    platform = "node",
    platformInfo = null,
  } = options;

  let runtimePromise = null;
  let requestQueue = Promise.resolve();

  async function boot() {
    assertSupportedNode();
    const pyodide = await loadPyodide();
    pyodide.FS.mkdirTree("/night");

    for (const name of ["night.py", "night_web.py", "app.py"]) {
      const source = await readFile(sourceLocation(sourceDir, name), "utf8");
      pyodide.FS.writeFile(`/night/${name}`, source, { encoding: "utf8" });
    }

    try {
      const infoSource = await readFile(sourceLocation(sourceDir, "night_request_info.py"), "utf8");
      pyodide.FS.writeFile("/night/night_request_info.py", infoSource, { encoding: "utf8" });
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
    }

    await pyodide.runPythonAsync(`
import sys
sys.path.insert(0, "/night")
from app import app as _night_app
from night_web import handle_web as _night_handle_web
`);
    return pyodide;
  }

  async function execute(request, context) {
    if (!(request instanceof Request)) {
      throw new TypeError("Night Node handler expects a Web-standard Request");
    }

    const pyodide = await (runtimePromise ??= boot());
    const method = request.method.toUpperCase();
    const body = method === "GET" || method === "HEAD"
      ? []
      : Array.from(new Uint8Array(await request.arrayBuffer()));
    const headers = [...request.headers.entries()];

    const extra = typeof platformInfo === "function"
      ? await platformInfo(context, request)
      : platformInfo;
    const info = { platform, ...toPlainPlatformInfo(extra) };

    pyodide.globals.set("_night_method", method);
    pyodide.globals.set("_night_url", request.url);
    pyodide.globals.set("_night_headers", headers);
    pyodide.globals.set("_night_body", body);
    pyodide.globals.set("_night_platform_info", info);

    const result = await pyodide.runPythonAsync(`
_headers = _night_headers.to_py() if hasattr(_night_headers, "to_py") else _night_headers
_body_value = _night_body.to_py() if hasattr(_night_body, "to_py") else _night_body
_info = _night_platform_info.to_py() if hasattr(_night_platform_info, "to_py") else _night_platform_info
_result = await _night_handle_web(
    _night_app,
    method=str(_night_method),
    url=str(_night_url),
    headers=_headers,
    body=bytes(_body_value),
    platform_info=dict(_info),
)
_result.as_tuple()
`);

    try {
      const js = result.toJs({ create_proxies: false });
      const status = Number(js[0]);
      const responseHeaders = responseHeadersFromPairs(js[1]);
      const responseBody = js[2] instanceof Uint8Array ? js[2] : new Uint8Array(js[2]);
      return new Response(responseBody, { status, headers: responseHeaders });
    } finally {
      result.destroy?.();
    }
  }

  async function handler(request, context = undefined) {
    const task = requestQueue.then(
      () => execute(request, context),
      () => execute(request, context),
    );
    requestQueue = task.then(() => undefined, () => undefined);
    return task;
  }

  handler.ready = async () => {
    await (runtimePromise ??= boot());
  };
  return handler;
}
