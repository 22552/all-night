import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { loadPyodide } from "pyodide";

export const NIGHT_NODE_SUPPORT = Object.freeze({
  node: ">=22",
  tested: [22, 24],
  pyodide: "0.28.3",
});

function assertSupportedNode() {
  const major = Number.parseInt(process.versions.node.split(".", 1)[0], 10);
  if (!Number.isFinite(major) || major < 22) {
    throw new Error(`Night's Node runtime requires Node.js 22+; got ${process.versions.node}`);
  }
}

async function readAppSource({ appSource, appFile }) {
  if (appSource != null) return String(appSource);
  return readFile(resolve(String(appFile ?? "app.py")), "utf8");
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
 * The Python framework is installed into Pyodide once per Node process and the
 * same runtime is reused for later requests. This keeps Night's transport
 * boundary at Web Request -> Night -> Web Response while leaving the Python
 * routing/core unchanged.
 */
export function createNightNodeHandler(options = {}) {
  const {
    appFile = "app.py",
    appSource = null,
    nightVersion = "0.1.2",
    platform = "node",
    platformInfo = null,
    pythonPackages = [],
  } = options;

  let runtimePromise = null;

  async function boot() {
    assertSupportedNode();
    const pyodide = await loadPyodide();
    await pyodide.loadPackage("micropip");

    const packageSpecs = [`all-night==${nightVersion}`, ...pythonPackages.map(String)];
    pyodide.globals.set("_night_package_specs", packageSpecs);
    await pyodide.runPythonAsync(`
import micropip
_specs = _night_package_specs.to_py() if hasattr(_night_package_specs, "to_py") else list(_night_package_specs)
await micropip.install(list(_specs))
`);

    const source = await readAppSource({ appSource, appFile });
    pyodide.FS.mkdirTree("/night_node");
    pyodide.FS.writeFile("/night_node/app.py", source);
    await pyodide.runPythonAsync(`
import sys
sys.path.insert(0, "/night_node")
from app import app as _night_app
from night_web import handle_web as _night_handle_web
`);
    return pyodide;
  }

  async function handler(request, context = undefined) {
    if (!(request instanceof Request)) {
      throw new TypeError("Night Node handler expects a Web-standard Request");
    }

    const pyodide = await (runtimePromise ??= boot());
    const method = request.method.toUpperCase();
    const body = method === "GET" || method === "HEAD"
      ? new Uint8Array()
      : new Uint8Array(await request.arrayBuffer());
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

  handler.ready = async () => {
    await (runtimePromise ??= boot());
  };
  handler.reset = () => {
    runtimePromise = null;
  };
  return handler;
}
